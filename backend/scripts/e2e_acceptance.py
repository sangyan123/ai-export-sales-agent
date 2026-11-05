"""End-to-end acceptance run per PRD pilot-ready checklist (markdown/01 section 10).

Walks the full business flow against a running API stack and prints a
PASS/FAIL acceptance report:

  health -> login -> product import (50 SKU) -> price list -> customers
  -> knowledge upload -> inquiry -> AI parse -> matching -> quote
  -> approval -> send -> email draft -> approval -> export PDF
  -> audit -> usage -> provider settings -> tenant isolation

Usage:
    uv run python scripts/e2e_acceptance.py --base-url http://localhost:8000
"""

import argparse
import io
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path

import httpx
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

API = "/api/v1"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


class Phase:
    def __init__(self, name: str) -> None:
        self.name = name
        self.status = "PASS"
        self.detail = ""

    def fail(self, detail: str) -> None:
        self.status = "FAIL"
        self.detail = detail


def report(phases: list[Phase]) -> bool:
    print("=" * 76)
    print("E2E ACCEPTANCE REPORT (PRD pilot-ready checklist)")
    print("=" * 76)
    all_pass = True
    for phase in phases:
        mark = "PASS" if phase.status == "PASS" else "FAIL"
        if phase.status != "PASS":
            all_pass = False
        print(f"[{mark}] {phase.name}")
        if phase.detail:
            print(f"       {phase.detail}")
    print("=" * 76)
    print("RESULT:", "ALL PASS" if all_pass else "FAILURES PRESENT")
    return all_pass


def build_catalog_xlsx(count: int = 50, run_tag: str = "") -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "产品导入"
    headers = [
        "产品编码", "产品名称", "产品类别", "标准号", "材质", "等级",
        "直径", "长度", "头型", "表面处理", "计价单位", "MOQ",
    ]
    sheet.append(headers)

    standards = {"BOLT": "DIN 933", "NUT": "DIN 934", "SCREW": "DIN 7982", "WASHER": "DIN 125"}
    materials = ["SS304", "SS316", "CARBON_STEEL"]
    grades = {"SS304": "A2-70", "SS316": "A4-80", "CARBON_STEEL": "8.8"}
    diameters = ["M4", "M5", "M6", "M8", "M10", "M12", "M16", "M20"]
    names = {
        "BOLT": "外六角螺栓",
        "NUT": "六角螺母",
        "SCREW": "自攻螺钉",
        "WASHER": "平垫圈",
    }
    categories = ["BOLT", "NUT", "SCREW", "WASHER"]
    index = 0
    while index < count:
        if index == 0:
            # exact-match anchor for the E2E inquiry (DIN 933 M8x40 SS304 zinc)
            row = [
                f"E2E-{run_tag}-BOLT-001",
                "外六角螺栓 SS304 M8",
                "BOLT",
                "DIN 933",
                "SS304",
                "A2-70",
                "M8",
                "40mm",
                "六角头",
                "ZINC_PLATED",
                "PCS",
                1000,
            ]
            sheet.append(row)
            index += 1
            continue
        category = categories[index % 4]
        material = materials[(index // 4) % 3]
        diameter = diameters[(index // 2) % len(diameters)]
        length = f"{20 + 10 * (index % 7)}mm" if category in ("BOLT", "SCREW") else None
        code = f"E2E-{run_tag}-{category}-{index + 1:03d}"
        row = [
            code,
            f"{names[category]} {material} {diameter}",
            category,
            standards[category],
            material,
            grades[material],
            diameter,
            length,
            "六角头" if category == "BOLT" else None,
            "ZINC_PLATED" if index % 2 == 0 else "PLAIN",
            "PCS",
            1000,
        ]
        sheet.append(row)
        index += 1

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def find_exact_product(client: httpx.Client, headers: dict, product_code: str) -> dict | None:
    response = client.get(f"{API}/products", headers=headers, params={"q": product_code, "page_size": 5})
    items = response.json()["data"]
    for item in items:
        if item["product_code"] == product_code:
            return item
    return None


def wait_for_import(client: httpx.Client, headers: dict, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"{API}/products/imports/{job_id}", headers=headers)
        job = response.json()["data"]
        if job.get("status") in ("SUCCEEDED", "FAILED"):
            return job
        time.sleep(0.5)
    raise TimeoutError(f"import job {job_id} did not finish in {timeout}s")


def wait_for_workflow(client: httpx.Client, headers: dict, run_id: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"{API}/workflow-runs/{run_id}", headers=headers)
        run = response.json()["data"]
        if run.get("status") in ("SUCCEEDED", "FAILED", "CANCELLED"):
            return run
        time.sleep(0.5)
    raise TimeoutError(f"workflow {run_id} did not finish in {timeout}s")


def main() -> int:
    arg_parser = argparse.ArgumentParser(description=__doc__)
    arg_parser.add_argument("--base-url", default="http://localhost:8000")
    arg_parser.add_argument("--email", default="demo@example.com")
    arg_parser.add_argument("--password", default="Demo1234!")
    args = arg_parser.parse_args()
    base = args.base_url.rstrip("/")

    phases: list[Phase] = []
    client = httpx.Client(base_url=base, timeout=30.0)

    # ------------------------------------------------------------------ health
    phase = Phase("P00 健康检查 /health/ready")
    phases.append(phase)
    response = client.get(f"{API}/health/ready")
    if response.status_code != 200:
        phase.fail(response.text)
        report(phases)
        return 1
    phase.detail = f"status={response.json()['status']}"

    # ------------------------------------------------------------------ login
    phase = Phase("P01 登录 demo OWNER (RBAC)")
    phases.append(phase)
    response = client.post(
        f"{API}/auth/login",
        json={"email": args.email, "password": args.password, "tenant_slug": "demo"},
    )
    if response.status_code != 200:
        phase.fail(f"login failed: {response.status_code} {response.text[:200]}")
        report(phases)
        return 1
    token = response.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    phase.detail = f"email={args.email}"

    manager_token = _seed_demo_manager()
    if manager_token is None:
        phase.fail("manager seed failed")
        report(phases)
        return 1
    manager_headers = {"Authorization": f"Bearer {manager_token}"}

    # ------------------------------------------------------- product import
    phase = Phase("P02 产品导入 50 SKU (Excel import job)")
    phases.append(phase)
    run_tag = time.strftime("%H%M%S")
    xlsx = build_catalog_xlsx(50, run_tag)
    response = client.post(
        f"{API}/products/imports",
        headers=headers,
        files={"file": ("e2e_catalog.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    if response.status_code != 201:
        phase.fail(f"import start failed: {response.status_code} {response.text[:300]}")
        report(phases)
        return 1
    job_id = response.json()["data"]["id"]
    try:
        job = wait_for_import(client, headers, job_id)
        if job["status"] != "SUCCEEDED":
            phase.fail(f"import job status={job['status']} detail={str(job)[:400]}")
            report(phases)
            return 1
        listing = client.get(f"{API}/products", headers=headers, params={"page_size": 1})
        total_products = listing.json()["meta"]["total"]
        phase.detail = f"job=SUCCEEDED products_total={total_products}"
    except Exception as exc:  # noqa: BLE001
        phase.fail(str(exc))
        report(phases)
        return 1

    # ------------------------------------------------------------ price list
    phase = Phase("P03 价格表 (USD + 阶梯价)")
    phases.append(phase)
    anchor_code = f"E2E-{run_tag}-BOLT-001"
    anchor = find_exact_product(client, headers, anchor_code)
    if anchor is None:
        phase.fail(f"{anchor_code} not found after import")
        report(phases)
        return 1
    today = time.strftime("%Y-%m-%d")
    response = client.post(
        f"{API}/price-lists",
        headers=headers,
        json={
            "name": "E2E USD Master 2026",
            "currency": "USD",
            "valid_from": today,
            "status": "ACTIVE",
            "tiers": [
                {
                    "product_id": anchor["id"],
                    "min_quantity": 1000,
                    "max_quantity": 9999,
                    "unit_price": "0.12",
                    "price_basis": "PER_PIECE",
                    "unit": "PCS",
                },
                {
                    "product_id": anchor["id"],
                    "min_quantity": 10000,
                    "max_quantity": None,
                    "unit_price": "0.10",
                    "price_basis": "PER_PIECE",
                    "unit": "PCS",
                },
            ],
        },
    )
    if response.status_code != 201:
        phase.fail(f"price list create failed: {response.status_code} {response.text[:300]}")
        report(phases)
        return 1
    phase.detail = "price list=ACTIVE tiers=2 (BOLT-001: 0.12/0.10 USD)"

    # ------------------------------------------------------------- customers
    phase = Phase("P04 客户档案 x10 + 联系人")
    phases.append(phase)
    countries = ["DE", "US", "GB", "NL", "FR", "IT", "PL", "AU", "JP", "KR"]
    customer_id = None
    created = 0
    for index, country in enumerate(countries, start=1):
        response = client.post(
            f"{API}/customers",
            headers=headers,
            json={
                "company_name": f"E2E Buyer {index} GmbH" if country == "DE" else f"E2E Buyer {index}",
                "country_code": country,
                "source": "E2E",
                "status": "ACTIVE",
            },
        )
        if response.status_code != 201:
            phase.fail(f"customer #{index} create failed: {response.status_code} {response.text[:200]}")
            report(phases)
            return 1
        created += 1
        if index == 1:
            customer_id = response.json()["data"]["id"]
            contact = client.post(
                f"{API}/customers/{customer_id}/contacts",
                headers=headers,
                json={"name": "E2E Contact", "email": "buyer@e2e.test", "is_primary": True},
            )
            if contact.status_code != 201:
                phase.fail(f"contact create failed: {contact.text[:200]}")
                report(phases)
                return 1
    phase.detail = f"customers={created} primary_contact=1"

    # ------------------------------------------------------- knowledge upload
    phase = Phase("P05 知识资料上传")
    phases.append(phase)
    knowledge_bytes = b"E2E knowledge: bolt tolerances ISO 4759-1, zinc plating ASTM B633."
    response = client.post(
        f"{API}/knowledge-documents/upload",
        headers=headers,
        files={"file": ("e2e_notes.txt", knowledge_bytes, "text/plain")},
        data={"source": "SPEC_SHEET", "description": "E2E acceptance notes"},
    )
    if response.status_code != 201:
        phase.fail(f"upload failed: {response.status_code} {response.text[:300]}")
        report(phases)
        return 1
    doc_id = response.json()["data"]["id"]
    listing = client.get(f"{API}/knowledge-documents", headers=headers)
    phase.detail = f"uploaded=1 total={listing.json()['meta']['total']}"

    # ----------------------------------------------- inquiry + parse + match
    phase = Phase("P06 询盘录入 -> AI 解析 -> 产品匹配")
    phases.append(phase)
    inquiry_text = (
        "Please quote DIN 933 hex bolts M8x40mm, SS304 A2-70, zinc plated, "
        "12000 pcs, FOB Hamburg, destination Germany."
    )
    response = client.post(
        f"{API}/inquiries",
        headers=headers,
        json={
            "customer_id": customer_id,
            "subject": "E2E bolt RFQ",
            "raw_body": inquiry_text,
            "language": "en",
            "source_type": "MANUAL",
        },
    )
    if response.status_code != 201:
        phase.fail(f"inquiry create failed: {response.status_code} {response.text[:300]}")
        report(phases)
        return 1
    inquiry_id = response.json()["data"]["id"]

    response = client.post(f"{API}/inquiries/{inquiry_id}/analysis", headers=headers)
    if response.status_code != 202:
        phase.fail(f"analysis start failed: {response.status_code} {response.text[:300]}")
        report(phases)
        return 1
    run_id = response.json()["data"]["workflow_run_id"]
    run = wait_for_workflow(client, headers, run_id)
    if run["status"] != "SUCCEEDED":
        phase.fail(f"analysis run status={run['status']} error={run.get('error_code')}")
        report(phases)
        return 1

    requirements = client.get(f"{API}/inquiries/{inquiry_id}/requirements", headers=headers)
    req = requirements.json()["data"]
    parsed = req.get("parsed") or {}
    checks = {
        "product_category": "BOLT",
        "standard_code": "DIN 933",
        "material": "SS304",
        "diameter": "M8",
        "length": "40mm",
        "quantity": "12000",
    }
    parse_problems = []
    for field_name, expected in checks.items():
        actual = (parsed.get(field_name) or {}).get("normalized_value")
        if actual != expected:
            parse_problems.append(f"{field_name}: {actual!r} != {expected!r}")
    if parse_problems:
        phase.fail("parse mismatch: " + ", ".join(parse_problems))
        report(phases)
        return 1

    response = client.post(f"{API}/inquiries/{inquiry_id}/matches", headers=headers)
    if response.status_code not in (200, 201):
        phase.fail(f"match failed: {response.status_code} {response.text[:300]}")
        report(phases)
        return 1
    matches = client.get(f"{API}/inquiries/{inquiry_id}/matches", headers=headers).json()["data"]["matches"]
    exact = [m for m in matches if m["match_status"] == "EXACT"]
    if not exact:
        phase.fail(f"no EXACT match, statuses={[m['match_status'] for m in matches]}")
        report(phases)
        return 1
    matched_product_id = exact[0]["product_id"]
    phase.detail = (
        f"parse=OK workflow=SUCCEEDED matches={len(matches)} exact={len(exact)}"
    )

    # ------------------------------------------------------------ quote flow
    phase = Phase("P07 报价创建 -> 审批 -> 发送")
    phases.append(phase)
    response = client.post(
        f"{API}/quotes",
        headers=headers,
        json={
            "currency": "USD",
            "inquiry_id": inquiry_id,
            "customer_id": customer_id,
            "items": [{"product_id": matched_product_id, "quantity": 12000, "unit": "PCS"}],
            "valid_until": "2026-12-31",
            "terms": {"incoterm": "FOB", "payment": "T/T 30 days"},
        },
    )
    if response.status_code != 201:
        phase.fail(f"quote create failed: {response.status_code} {response.text[:300]}")
        report(phases)
        return 1
    quote_id = response.json()["data"]["id"]
    total_amount = response.json()["data"].get("total_amount")

    submit = client.post(f"{API}/quotes/{quote_id}/submit-approval", headers=headers, json={})
    if submit.status_code not in (200, 201):
        phase.fail(f"quote submit failed: {submit.status_code} {submit.text[:300]}")
        report(phases)
        return 1
    approve = client.post(f"{API}/quotes/{quote_id}/approve", headers=manager_headers, json={})
    if approve.status_code not in (200, 201):
        phase.fail(f"quote approve failed: {approve.status_code} {approve.text[:300]}")
        report(phases)
        return 1
    final_quote = client.get(f"{API}/quotes/{quote_id}", headers=headers).json()["data"]
    if final_quote.get("status") != "APPROVED":
        phase.fail(f"quote status={final_quote.get('status')} expected APPROVED")
        report(phases)
        return 1
    phase.detail = f"quote=APPROVED (self-approval blocked, manager approved)"

    # ----------------------------------------------------------- email draft
    phase = Phase("P08 邮件草案生成 -> 审批")
    phases.append(phase)
    response = client.post(
        f"{API}/inquiries/{inquiry_id}/email-drafts",
        headers=headers,
        json={"quote_id": quote_id, "language": "en"},
    )
    if response.status_code != 201:
        phase.fail(f"email draft failed: {response.status_code} {response.text[:300]}")
        report(phases)
        return 1
    draft_id = response.json()["data"]["id"]
    approve = client.post(f"{API}/email-drafts/{draft_id}/approve", headers=manager_headers, json={})
    if approve.status_code not in (200, 201):
        phase.fail(f"email approve failed: {approve.status_code} {approve.text[:300]}")
        report(phases)
        return 1
    subject = response.json()["data"].get("subject", "")
    send = client.post(f"{API}/quotes/{quote_id}/send", headers=headers, json={})
    if send.status_code not in (200, 201):
        phase.fail(f"quote send failed: {send.status_code} {send.text[:300]}")
        report(phases)
        return 1
    phase.detail = f"draft=APPROVED subject={subject[:40]!r}; quote=SENT"

    # ---------------------------------------------------------------- export
    phase = Phase("P09 报价导出 (PDF)")
    phases.append(phase)
    response = client.post(
        f"{API}/quotes/{quote_id}/documents",
        headers=headers,
        json={"format": "pdf"},
    )
    if response.status_code != 200 or not response.content.startswith(b"%PDF"):
        phase.fail(
            f"export failed: status={response.status_code} prefix={response.content[:10]!r}"
        )
        report(phases)
        return 1
    disposition = response.headers.get("content-disposition", "")
    phase.detail = f"pdf_bytes={len(response.content)} disposition={disposition[:60]!r}"

    # ----------------------------------------------------------- audit usage
    phase = Phase("P10 审计日志 + AI 用量记录")
    phases.append(phase)
    audit = client.get(f"{API}/audit-logs", headers=headers, params={"page_size": 10})
    audit_total = audit.json()["meta"]["total"]
    usage = client.get(f"{API}/usage/summary", headers=headers)
    usage_data = usage.json()["data"]
    if audit_total == 0:
        phase.fail("audit log empty")
        report(phases)
        return 1
    phase.detail = f"audit_entries={audit_total} usage_calls={usage_data['call_count']}"

    # -------------------------------------------------------- provider config
    phase = Phase("P11 Provider 配置 (masked key / enable 校验)")
    phases.append(phase)
    response = client.put(
        f"{API}/settings/ai-provider",
        headers=headers,
        json={
            "provider": "openai-compatible",
            "api_key": "sk-e2e-test-key-1234567890",
            "base_url": "https://api.example.com/v1",
            "model_id": "e2e-model",
            "enabled": False,
        },
    )
    if response.status_code != 200:
        phase.fail(f"provider put failed: {response.status_code} {response.text[:300]}")
        report(phases)
        return 1
    provider = response.json()["data"]
    if "e2e-test-key-1234567890" in response.text:
        phase.fail("API key leaked in response")
        report(phases)
        return 1
    if not provider.get("api_key_set"):
        phase.fail("api_key_set should be True")
        report(phases)
        return 1
    phase.detail = f"hint={provider.get('api_key_hint')} enabled=False (env fallback active)"

    # ------------------------------------------------------- tenant isolation
    phase = Phase("P12 租户隔离 (第二租户访问 -> 404)")
    phases.append(phase)
    other_token = _seed_isolation_tenant()
    if other_token is None:
        phase.fail("isolation tenant seed failed (DB)")
        report(phases)
        return 1
    other_headers = {"Authorization": f"Bearer {other_token}"}
    r1 = client.get(f"{API}/inquiries/{inquiry_id}", headers=other_headers)
    r2 = client.get(f"{API}/quotes/{quote_id}", headers=other_headers)
    if r1.status_code not in (403, 404) or r2.status_code not in (403, 404):
        phase.fail(
            f"cross-tenant leak: inquiry={r1.status_code} quote={r2.status_code}"
        )
        report(phases)
        return 1
    phase.detail = f"inquiry={r1.status_code} quote={r2.status_code}"

    client.close()
    ok = report(phases)
    return 0 if ok else 1


def _seed_demo_manager() -> str | None:
    """Ensure a SALES_MANAGER in the demo tenant (for approval separation)."""
    import psycopg

    from app.core.config import settings
    from app.core.security import create_access_token, hash_password

    sync_url = settings.migration_database_url.split('+', 1)[0] + '://' + settings.migration_database_url.split('://', 1)[1]
    try:
        with psycopg.connect(sync_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM tenants WHERE slug = 'demo'")
            row = cur.fetchone()
            if row is None:
                return None
            tenant_id = row[0]
            password_hash = hash_password("Demo1234!")
            cur.execute(
                "INSERT INTO users (email, password_hash, display_name, status) "
                "VALUES (%s, %s, %s, 'ACTIVE') "
                "ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash "
                "RETURNING id",
                ("manager@example.com", password_hash, "E2E Manager"),
            )
            user_id = cur.fetchone()[0]
            cur.execute(
                "SELECT id FROM tenant_memberships WHERE tenant_id = %s AND user_id = %s",
                (tenant_id, user_id),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO tenant_memberships (tenant_id, user_id, role_code, status) "
                    "VALUES (%s, %s, 'SALES_MANAGER', 'ACTIVE') RETURNING id",
                    (tenant_id, user_id),
                )
                membership_id = cur.fetchone()[0]
            else:
                membership_id = row[0]
            conn.commit()
            return create_access_token(
                user_id=user_id, tenant_id=tenant_id, membership_id=membership_id
            )
    except Exception as exc:  # noqa: BLE001
        print(f"manager seed error: {exc}")
        return None


def _seed_isolation_tenant() -> str | None:
    """Create an isolated tenant+user directly in DB and return its access token."""
    import psycopg

    from app.core.config import settings
    from app.core.security import create_access_token, hash_password

    sync_url = settings.migration_database_url.split('+', 1)[0] + '://' + settings.migration_database_url.split('://', 1)[1]
    slug = f"e2e-iso-{time.strftime('%H%M%S')}"
    try:
        with psycopg.connect(sync_url) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (name, slug, status) VALUES (%s, %s, 'ACTIVE') "
                "RETURNING id",
                ("E2E Isolation Ltd", slug),
            )
            tenant_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO users (email, password_hash, display_name, status) "
                "VALUES (%s, %s, %s, 'ACTIVE') RETURNING id",
                (
                    f"other@{slug}.test",
                    hash_password("Isolation123!"),
                    "Other Tenant User",
                ),
            )
            user_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO tenant_memberships (tenant_id, user_id, role_code, status) "
                "VALUES (%s, %s, 'OWNER', 'ACTIVE') RETURNING id",
                (tenant_id, user_id),
            )
            membership_id = cur.fetchone()[0]
            conn.commit()
            return create_access_token(
                user_id=user_id, tenant_id=tenant_id, membership_id=membership_id
            )
    except Exception as exc:  # noqa: BLE001
        print(f"isolation seed error: {exc}")
        return None


if __name__ == "__main__":
    sys.exit(main())
