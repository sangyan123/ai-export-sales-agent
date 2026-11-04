import os
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.db.session import get_session
from app.db.tenant import set_tenant_context
from app.main import app
from app.models.pricing import PriceList, PriceTier
from app.models.product import Product
from app.models.quote import ApprovalTask
from app.models.tenant import Tenant, TenantMembership, User

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
PASSWORD_HASH = hash_password("test-password")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to run database integration tests",
)


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            factory = async_sessionmaker(bind=connection, expire_on_commit=False)
            async with factory() as session:
                yield session
            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
async def client(session: AsyncSession) -> AsyncClient:
    async def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_session, None)


@dataclass(frozen=True)
class ApiSeed:
    tenant: Tenant
    requester: User
    approver: User
    outsider: User
    product: Product
    unpriced_product: Product
    requester_headers: dict[str, str]
    approver_headers: dict[str, str]
    outsider_headers: dict[str, str]


def _bearer(tenant: Tenant, user: User, membership_id: uuid.UUID) -> dict[str, str]:
    token = create_access_token(
        user_id=user.id,
        tenant_id=tenant.id,
        membership_id=membership_id,
    )
    return {"Authorization": f"Bearer {token}"}


async def seed_api(session: AsyncSession, slug: str) -> ApiSeed:
    tenant = Tenant(name=slug, slug=slug)
    session.add(tenant)
    await session.flush()
    await set_tenant_context(session, tenant.id)

    requester = User(
        email=f"rep@{slug}.example", password_hash=PASSWORD_HASH, display_name="Sales Rep"
    )
    approver = User(
        email=f"approver@{slug}.example", password_hash=PASSWORD_HASH, display_name="Approver"
    )
    outsider = User(
        email=f"outsider@{slug}.example", password_hash=PASSWORD_HASH, display_name="Outsider"
    )
    session.add_all([requester, approver, outsider])
    await session.flush()
    requester_membership = TenantMembership(
        tenant_id=tenant.id, user_id=requester.id, role_code="SALES_MANAGER"
    )
    approver_membership = TenantMembership(
        tenant_id=tenant.id, user_id=approver.id, role_code="APPROVER"
    )
    session.add_all([requester_membership, approver_membership])
    await session.flush()

    product = Product(
        tenant_id=tenant.id,
        product_code="BOLT-M8-30",
        product_name="Hex bolt M8x30 SS304",
        category="BOLT",
        sales_unit="PCS",
        moq=Decimal("1000"),
    )
    unpriced_product = Product(
        tenant_id=tenant.id,
        product_code="NUT-M8",
        product_name="Hex nut M8 SS304",
        category="NUT",
        sales_unit="PCS",
    )
    price_list = PriceList(
        tenant_id=tenant.id,
        name="2026 USD",
        currency="USD",
        valid_from=date(2026, 1, 1),
        status="ACTIVE",
        version=1,
    )
    session.add_all([product, unpriced_product, price_list])
    await session.flush()
    session.add(
        PriceTier(
            tenant_id=tenant.id,
            price_list_id=price_list.id,
            product_id=product.id,
            min_quantity=Decimal("1"),
            unit_price=Decimal("2.2000"),
            price_basis="PER_PIECE",
            unit="PCS",
        )
    )
    await session.flush()

    return ApiSeed(
        tenant=tenant,
        requester=requester,
        approver=approver,
        outsider=outsider,
        product=product,
        unpriced_product=unpriced_product,
        requester_headers=_bearer(tenant, requester, requester_membership.id),
        approver_headers=_bearer(tenant, approver, approver_membership.id),
        outsider_headers=_bearer(tenant, outsider, uuid.uuid4()),
    )


def quote_payload(seed: ApiSeed, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "currency": "USD",
        "items": [
            {
                "product_id": str(seed.product.id),
                "quantity": "1000",
                "unit": "PCS",
            }
        ],
        "valid_until": "2026-12-31",
        "terms": {"payment_terms": "T/T 30% deposit"},
    }
    payload.update(overrides)
    return payload


async def create_quote(client: AsyncClient, seed: ApiSeed, **overrides: Any) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/quotes",
        json=quote_payload(seed, **overrides),
        headers=seed.requester_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def set_policy(client: AsyncClient, seed: ApiSeed, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "rounding_mode": "ROUND_HALF_UP",
        "rounding_decimal_places": None,
        "moq_enforcement": "WARN",
        "max_discount_percent": "100",
    }
    payload.update(overrides)
    response = await client.put(
        "/api/v1/tenants/current/pricing-policy",
        json=payload,
        headers=seed.requester_headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_create_quote_returns_snapshot_and_echoes_request_id(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-create")

    response = await client.post(
        "/api/v1/quotes",
        json=quote_payload(seed),
        headers={**seed.requester_headers, "X-Request-ID": "req_test_create"},
    )

    assert response.status_code == 201
    assert response.headers["X-Request-ID"] == "req_test_create"
    body = response.json()
    assert body["meta"]["request_id"] == "req_test_create"
    data = body["data"]
    assert data["status"] == "DRAFT"
    assert data["currency"] == "USD"
    assert data["subtotal"] == "2200.0000"
    assert data["grand_total"] == "2200.0000"
    assert data["grand_total_display"] == "2200.00"
    assert data["terms"] == {"payment_terms": "T/T 30% deposit"}
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["line_no"] == 1
    assert item["product_snapshot"]["product_code"] == "BOLT-M8-30"
    assert item["price_source_ref"]["kind"] == "PRICE_LIST"
    assert [event["event_type"] for event in data["events"]] == ["CREATED"]


async def test_quote_request_requires_bearer_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/quotes")

    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "AUTH_REQUIRED"
    assert error["request_id"].startswith("req_")


async def test_non_member_cannot_access_tenant(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_api(session, "api-outsider")

    response = await client.get("/api/v1/quotes", headers=seed.outsider_headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "TENANT_ACCESS_DENIED"


async def test_list_quotes_paginates_and_filters(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-list")
    await create_quote(client, seed, quote_no="Q-LIST-1")
    await create_quote(client, seed, quote_no="Q-LIST-2")

    first_page = await client.get(
        "/api/v1/quotes",
        params={"page": 1, "page_size": 1},
        headers=seed.requester_headers,
    )
    assert first_page.status_code == 200
    body = first_page.json()
    assert body["meta"]["page"] == 1
    assert body["meta"]["page_size"] == 1
    assert body["meta"]["total"] == 2
    assert len(body["data"]) == 1

    drafts = await client.get(
        "/api/v1/quotes",
        params={"status": "DRAFT"},
        headers=seed.requester_headers,
    )
    assert drafts.status_code == 200
    assert drafts.json()["meta"]["total"] == 2

    approved = await client.get(
        "/api/v1/quotes",
        params={"status": "APPROVED"},
        headers=seed.requester_headers,
    )
    assert approved.status_code == 200
    assert approved.json()["meta"]["total"] == 0


async def test_get_quote_detail_includes_items_and_events(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-detail")
    created = await create_quote(client, seed)

    response = await client.get(f"/api/v1/quotes/{created['id']}", headers=seed.requester_headers)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == created["id"]
    assert data["quote_no"] == created["quote_no"]
    assert data["items"][0]["quantity"] == "1000.0000"
    assert [event["event_type"] for event in data["events"]] == ["CREATED"]


async def test_submit_and_approve_lifecycle(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_api(session, "api-approve")
    created = await create_quote(client, seed)

    submitted = await client.post(
        f"/api/v1/quotes/{created['id']}/submit-approval",
        headers=seed.requester_headers,
    )
    assert submitted.status_code == 200
    assert submitted.json()["data"]["status"] == "PENDING_APPROVAL"
    assert submitted.json()["data"]["events"][-1]["event_type"] == "SUBMITTED"

    task = await session.scalar(select(ApprovalTask).where(ApprovalTask.object_id == created["id"]))
    assert task is not None
    assert task.status == "PENDING"
    assert task.requested_by == seed.requester.id

    approved = await client.post(
        f"/api/v1/quotes/{created['id']}/approve",
        json={"decision_note": "prices verified"},
        headers=seed.approver_headers,
    )
    assert approved.status_code == 200
    data = approved.json()["data"]
    assert data["status"] == "APPROVED"
    assert [event["event_type"] for event in data["events"]] == [
        "CREATED",
        "SUBMITTED",
        "APPROVED",
    ]
    assert data["events"][-1]["event_payload"]["note"] == "prices verified"

    await session.refresh(task)
    assert task.status == "APPROVED"
    assert task.approver_id == seed.approver.id
    assert task.decision_note == "prices verified"


async def test_requester_cannot_approve_own_quote(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-self-approve")
    created = await create_quote(client, seed)
    await client.post(
        f"/api/v1/quotes/{created['id']}/submit-approval",
        headers=seed.requester_headers,
    )

    response = await client.post(
        f"/api/v1/quotes/{created['id']}/approve",
        headers=seed.requester_headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SELF_APPROVAL_FORBIDDEN"


async def test_rejected_quote_cannot_be_resubmitted(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-reject")
    created = await create_quote(client, seed)
    await client.post(
        f"/api/v1/quotes/{created['id']}/submit-approval",
        headers=seed.requester_headers,
    )

    rejected = await client.post(
        f"/api/v1/quotes/{created['id']}/reject",
        json={"decision_note": "discount too high"},
        headers=seed.approver_headers,
    )
    assert rejected.status_code == 200
    assert rejected.json()["data"]["status"] == "REJECTED"

    resubmit = await client.post(
        f"/api/v1/quotes/{created['id']}/submit-approval",
        headers=seed.requester_headers,
    )
    assert resubmit.status_code == 409
    assert resubmit.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


async def test_cancel_quote(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_api(session, "api-cancel")
    created = await create_quote(client, seed)

    response = await client.post(
        f"/api/v1/quotes/{created['id']}/cancel",
        json={"note": "customer withdrew"},
        headers=seed.requester_headers,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "CANCELLED"
    assert data["events"][-1]["event_type"] == "CANCELLED"
    assert data["events"][-1]["event_payload"] == {"note": "customer withdrew"}


async def test_quote_is_not_visible_to_another_tenant(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed_a = await seed_api(session, "api-tenant-a")
    seed_b = await seed_api(session, "api-tenant-b")
    created = await create_quote(client, seed_a)

    response = await client.get(f"/api/v1/quotes/{created['id']}", headers=seed_b.requester_headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "QUOTE_NOT_FOUND"


async def test_unpriced_product_returns_pricing_error(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-unpriced")

    response = await client.post(
        "/api/v1/quotes",
        json=quote_payload(
            seed,
            items=[
                {
                    "product_id": str(seed.unpriced_product.id),
                    "quantity": "100",
                    "unit": "PCS",
                }
            ],
        ),
        headers=seed.requester_headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PRICE_MISSING"


async def test_unknown_product_returns_not_found(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-missing-product")

    response = await client.post(
        "/api/v1/quotes",
        json=quote_payload(
            seed,
            items=[
                {
                    "product_id": "00000000-0000-0000-0000-000000000000",
                    "quantity": "1",
                    "unit": "PCS",
                }
            ],
        ),
        headers=seed.requester_headers,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PRODUCT_NOT_FOUND"


async def test_duplicate_quote_version_returns_conflict(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-duplicate")
    await create_quote(client, seed, quote_no="Q-DUP", version_no=1)

    response = await client.post(
        "/api/v1/quotes",
        json=quote_payload(seed, quote_no="Q-DUP", version_no=1),
        headers=seed.requester_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "QUOTE_VERSION_EXISTS"


async def test_validation_error_uses_error_envelope(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-validation")

    response = await client.post(
        "/api/v1/quotes",
        json={"currency": "USD", "items": []},
        headers=seed.requester_headers,
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert any(detail["field"] == "items" for detail in error["details"])


async def approve_quote(client: AsyncClient, seed: ApiSeed, quote_id: str) -> dict[str, Any]:
    submitted = await client.post(
        f"/api/v1/quotes/{quote_id}/submit-approval",
        headers=seed.requester_headers,
    )
    assert submitted.status_code == 200, submitted.text
    approved = await client.post(
        f"/api/v1/quotes/{quote_id}/approve",
        headers=seed.approver_headers,
    )
    assert approved.status_code == 200, approved.text
    return approved.json()["data"]


async def test_recalculate_reprices_with_current_price(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-recalculate")
    created = await create_quote(client, seed)

    tier = await session.scalar(select(PriceTier).where(PriceTier.product_id == seed.product.id))
    assert tier is not None
    tier.unit_price = Decimal("2.3000")
    await session.flush()

    response = await client.post(
        f"/api/v1/quotes/{created['id']}/recalculate",
        json={"price_as_of": "2026-11-03"},
        headers=seed.requester_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["grand_total"] == "2300.0000"
    assert data["items"][0]["unit_price"] == "2.3000"
    assert data["events"][-1]["event_type"] == "REVISED"
    assert data["events"][-1]["event_payload"] == {
        "action": "recalculate",
        "price_as_of": "2026-11-03",
        "grand_total": "2300.0000",
    }


async def test_recalculate_rejects_non_draft_quote(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-recalculate-approved")
    created = await create_quote(client, seed)
    await approve_quote(client, seed, created["id"])

    response = await client.post(
        f"/api/v1/quotes/{created['id']}/recalculate",
        headers=seed.requester_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


async def test_revise_rejected_quote_returns_to_draft(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-revise")
    created = await create_quote(client, seed)
    await client.post(
        f"/api/v1/quotes/{created['id']}/submit-approval",
        headers=seed.requester_headers,
    )
    rejected = await client.post(
        f"/api/v1/quotes/{created['id']}/reject",
        headers=seed.approver_headers,
    )
    assert rejected.status_code == 200

    response = await client.post(
        f"/api/v1/quotes/{created['id']}/revise",
        headers=seed.requester_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "DRAFT"
    assert data["events"][-1]["event_type"] == "REVISED"


async def test_send_quote_requires_submit_permission(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-send")
    created = await create_quote(client, seed)
    await approve_quote(client, seed, created["id"])

    denied = await client.post(
        f"/api/v1/quotes/{created['id']}/send",
        headers=seed.approver_headers,
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "PERMISSION_DENIED"

    sent = await client.post(
        f"/api/v1/quotes/{created['id']}/send",
        json={"note": "emailed to buyer"},
        headers=seed.requester_headers,
    )
    assert sent.status_code == 200, sent.text
    data = sent.json()["data"]
    assert data["status"] == "SENT"
    assert data["events"][-1]["event_type"] == "SENT"
    assert data["events"][-1]["event_payload"] == {"note": "emailed to buyer"}


async def test_expire_quote_after_validity(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_api(session, "api-expire")
    created = await create_quote(client, seed, valid_until="2026-10-31")
    await approve_quote(client, seed, created["id"])

    response = await client.post(
        f"/api/v1/quotes/{created['id']}/expire",
        json={"as_of": "2026-11-03"},
        headers=seed.requester_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "EXPIRED"
    assert data["events"][-1]["event_type"] == "EXPIRED"
    assert data["events"][-1]["event_payload"] == {"as_of": "2026-11-03"}


async def test_expire_rejects_valid_quote(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_api(session, "api-expire-early")
    created = await create_quote(client, seed)
    await approve_quote(client, seed, created["id"])

    response = await client.post(
        f"/api/v1/quotes/{created['id']}/expire",
        json={"as_of": "2026-11-03"},
        headers=seed.requester_headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDITY_NOT_REACHED"


async def test_generate_quote_pdf_and_xlsx(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_api(session, "api-documents")
    created = await create_quote(client, seed, quote_no="Q-DOC-1")

    pdf = await client.post(
        f"/api/v1/quotes/{created['id']}/documents",
        params={"format": "PDF"},
        headers=seed.requester_headers,
    )
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert 'filename="Q-DOC-1-v1.pdf"' in pdf.headers["content-disposition"]
    assert pdf.content.startswith(b"%PDF")

    xlsx = await client.post(
        f"/api/v1/quotes/{created['id']}/documents",
        params={"format": "XLSX"},
        headers=seed.requester_headers,
    )
    assert xlsx.status_code == 200
    assert xlsx.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert 'filename="Q-DOC-1-v1.xlsx"' in xlsx.headers["content-disposition"]
    assert xlsx.content.startswith(b"PK")


async def test_generate_quote_document_rejects_unknown_format(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-documents-invalid")
    created = await create_quote(client, seed)

    response = await client.post(
        f"/api/v1/quotes/{created['id']}/documents",
        params={"format": "DOCX"},
        headers=seed.requester_headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_create_version_copies_approved_quote(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-version")
    created = await create_quote(client, seed, quote_no="Q-VER-1")
    await approve_quote(client, seed, created["id"])

    response = await client.post(
        f"/api/v1/quotes/{created['id']}/versions",
        json={"valid_until": "2027-01-31"},
        headers=seed.requester_headers,
    )

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["id"] != created["id"]
    assert data["quote_no"] == "Q-VER-1"
    assert data["version_no"] == 2
    assert data["status"] == "DRAFT"
    assert data["grand_total"] == created["grand_total"]
    assert data["valid_until"] == "2027-01-31"
    assert data["created_by"] == str(seed.requester.id)
    assert len(data["items"]) == 1
    assert data["items"][0]["product_snapshot"] == created["items"][0]["product_snapshot"]
    assert data["items"][0]["unit_price"] == created["items"][0]["unit_price"]
    assert [event["event_type"] for event in data["events"]] == ["CREATED"]
    assert data["events"][0]["event_payload"]["source_quote_id"] == created["id"]
    assert data["events"][0]["event_payload"]["source_version_no"] == 1

    versions = await client.get(
        "/api/v1/quotes",
        params={"quote_no": "Q-VER-1"},
        headers=seed.requester_headers,
    )
    assert versions.status_code == 200
    assert versions.json()["meta"]["total"] == 2
    assert {item["version_no"] for item in versions.json()["data"]} == {1, 2}


async def test_create_version_requires_approved_quote(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-version-draft")
    created = await create_quote(client, seed)

    response = await client.post(
        f"/api/v1/quotes/{created['id']}/versions",
        headers=seed.requester_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


async def test_create_version_rejects_existing_next_version(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-version-duplicate")
    created = await create_quote(client, seed, quote_no="Q-VER-DUP")
    await approve_quote(client, seed, created["id"])
    first = await client.post(
        f"/api/v1/quotes/{created['id']}/versions",
        headers=seed.requester_headers,
    )
    assert first.status_code == 201, first.text

    response = await client.post(
        f"/api/v1/quotes/{created['id']}/versions",
        headers=seed.requester_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "QUOTE_VERSION_EXISTS"


async def test_create_version_requires_quote_create_permission(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-version-permission")
    created = await create_quote(client, seed)
    await approve_quote(client, seed, created["id"])

    response = await client.post(
        f"/api/v1/quotes/{created['id']}/versions",
        headers=seed.approver_headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_create_version_is_scoped_to_tenant(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed_a = await seed_api(session, "api-version-tenant-a")
    seed_b = await seed_api(session, "api-version-tenant-b")
    created = await create_quote(client, seed_a)
    await approve_quote(client, seed_a, created["id"])

    response = await client.post(
        f"/api/v1/quotes/{created['id']}/versions",
        headers=seed_b.requester_headers,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "QUOTE_NOT_FOUND"


async def test_quote_mutations_write_audit_log(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_api(session, "api-audit-quote")

    created = await client.post(
        "/api/v1/quotes",
        json=quote_payload(seed),
        headers={**seed.requester_headers, "X-Request-ID": "req_audit_create"},
    )
    assert created.status_code == 201, created.text
    quote_id = created.json()["data"]["id"]

    submitted = await client.post(
        f"/api/v1/quotes/{quote_id}/submit-approval",
        headers=seed.requester_headers,
    )
    assert submitted.status_code == 200, submitted.text

    response = await client.get(
        "/api/v1/audit-logs",
        params={"resource_type": "QUOTE", "resource_id": quote_id},
        headers=seed.requester_headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meta"]["total"] == 2
    actions = {entry["action"] for entry in body["data"]}
    assert actions == {"quote.create", "quote.submit"}
    create_entry = next(entry for entry in body["data"] if entry["action"] == "quote.create")
    assert create_entry["actor_id"] == str(seed.requester.id)
    assert create_entry["request_id"] == "req_audit_create"
    assert create_entry["ip_hash"] is not None
    assert create_entry["metadata"]["quote_no"] == created.json()["data"]["quote_no"]

    within_range = await client.get(
        "/api/v1/audit-logs",
        params={"created_from": "2000-01-01T00:00:00", "created_to": "2100-01-01T00:00:00"},
        headers=seed.requester_headers,
    )
    assert within_range.status_code == 200, within_range.text
    assert within_range.json()["meta"]["total"] == 2

    after_range = await client.get(
        "/api/v1/audit-logs",
        params={"created_from": "2100-01-01T00:00:00"},
        headers=seed.requester_headers,
    )
    assert after_range.status_code == 200
    assert after_range.json()["meta"]["total"] == 0


async def test_audit_logs_are_scoped_to_tenant_and_permission(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed_a = await seed_api(session, "api-audit-tenant-a")
    seed_b = await seed_api(session, "api-audit-tenant-b")
    await create_quote(client, seed_a)

    from_other_tenant = await client.get(
        "/api/v1/audit-logs",
        headers=seed_b.requester_headers,
    )
    assert from_other_tenant.status_code == 200
    assert from_other_tenant.json()["meta"]["total"] == 0

    denied = await client.get("/api/v1/audit-logs", headers=seed_a.approver_headers)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_pricing_policy_defaults_update_and_audit(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-policy")

    default = await client.get(
        "/api/v1/tenants/current/pricing-policy",
        headers=seed.approver_headers,
    )
    assert default.status_code == 200, default.text
    data = default.json()["data"]
    assert data["is_default"] is True
    assert data["rounding_mode"] == "ROUND_HALF_UP"
    assert data["rounding_decimal_places"] is None
    assert data["moq_enforcement"] == "WARN"
    assert data["max_discount_percent"] == "100.00"
    assert data["updated_by_id"] is None

    updated = await set_policy(
        client,
        seed,
        rounding_mode="ROUND_DOWN",
        rounding_decimal_places=2,
        moq_enforcement="BLOCK",
        max_discount_percent="12.50",
    )
    assert updated["is_default"] is False
    assert updated["rounding_mode"] == "ROUND_DOWN"
    assert updated["rounding_decimal_places"] == 2
    assert updated["moq_enforcement"] == "BLOCK"
    assert updated["max_discount_percent"] == "12.50"
    assert updated["updated_by_id"] == str(seed.requester.id)
    assert updated["updated_at"] is not None

    fetched = await client.get(
        "/api/v1/tenants/current/pricing-policy",
        headers=seed.requester_headers,
    )
    assert fetched.status_code == 200
    assert fetched.json()["data"] == updated

    denied = await client.put(
        "/api/v1/tenants/current/pricing-policy",
        json={
            "rounding_mode": "ROUND_HALF_UP",
            "rounding_decimal_places": None,
            "moq_enforcement": "WARN",
            "max_discount_percent": "100",
        },
        headers=seed.approver_headers,
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "PERMISSION_DENIED"

    audit = await client.get(
        "/api/v1/audit-logs",
        params={"resource_type": "PRICING_POLICY"},
        headers=seed.requester_headers,
    )
    assert audit.status_code == 200, audit.text
    assert audit.json()["meta"]["total"] == 1
    entry = audit.json()["data"][0]
    assert entry["action"] == "pricing.policy.updated"
    assert entry["actor_id"] == str(seed.requester.id)
    assert entry["metadata"]["policy"]["rounding_mode"] == "ROUND_DOWN"


async def test_pricing_policy_rounding_applies_to_quote(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-policy-rounding")
    tier = await session.scalar(select(PriceTier).where(PriceTier.product_id == seed.product.id))
    assert tier is not None
    tier.unit_price = Decimal("2.2250")
    await session.flush()

    await set_policy(
        client,
        seed,
        rounding_mode="ROUND_DOWN",
        rounding_decimal_places=2,
    )

    created = await create_quote(
        client,
        seed,
        items=[
            {
                "product_id": str(seed.product.id),
                "quantity": "1",
                "unit": "PCS",
            }
        ],
    )

    assert created["subtotal"] == "2.2250"
    assert created["subtotal_display"] == "2.22"
    assert created["grand_total"] == "2.2250"
    assert created["grand_total_display"] == "2.22"
    assert created["items"][0]["line_total"] == "2.2250"


async def test_pricing_policy_moq_block_rejects_quote_and_recalculate(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-policy-moq")
    below_moq_items = [
        {
            "product_id": str(seed.product.id),
            "quantity": "500",
            "unit": "PCS",
        }
    ]

    created = await create_quote(client, seed, items=below_moq_items)
    assert created["status"] == "DRAFT"

    await set_policy(client, seed, moq_enforcement="BLOCK")

    rejected = await client.post(
        "/api/v1/quotes",
        json=quote_payload(seed, items=below_moq_items),
        headers=seed.requester_headers,
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "MOQ_NOT_MET"

    recalculate = await client.post(
        f"/api/v1/quotes/{created['id']}/recalculate",
        headers=seed.requester_headers,
    )
    assert recalculate.status_code == 409
    assert recalculate.json()["error"]["code"] == "MOQ_NOT_MET"

    at_moq = await client.post(
        "/api/v1/quotes",
        json=quote_payload(seed),
        headers=seed.requester_headers,
    )
    assert at_moq.status_code == 201, at_moq.text


async def test_quote_create_persists_discount_and_charges(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-policy-charges")

    created = await create_quote(
        client,
        seed,
        discount_total="100",
        freight_total="50",
        other_charges="25",
    )

    assert created["subtotal"] == "2200.0000"
    assert created["discount_total"] == "100.0000"
    assert created["freight_total"] == "50.0000"
    assert created["other_charges"] == "25.0000"
    assert created["grand_total"] == "2175.0000"
    assert created["grand_total_display"] == "2175.00"


async def test_pricing_policy_discount_limit_enforced_on_submit(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_api(session, "api-policy-discount")
    await set_policy(client, seed, max_discount_percent="5")

    within_limit = await create_quote(client, seed, discount_total="100")
    submitted = await client.post(
        f"/api/v1/quotes/{within_limit['id']}/submit-approval",
        headers=seed.requester_headers,
    )
    assert submitted.status_code == 200, submitted.text

    over_limit = await create_quote(client, seed, discount_total="200")
    rejected = await client.post(
        f"/api/v1/quotes/{over_limit['id']}/submit-approval",
        headers=seed.requester_headers,
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "DISCOUNT_LIMIT_EXCEEDED"


async def test_pricing_policy_validates_values(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_api(session, "api-policy-validation")

    response = await client.put(
        "/api/v1/tenants/current/pricing-policy",
        json={
            "rounding_mode": "ROUND_DOWN",
            "rounding_decimal_places": 5,
            "moq_enforcement": "BLOCK",
            "max_discount_percent": "150",
        },
        headers=seed.requester_headers,
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    fields = {detail["field"] for detail in error["details"]}
    assert {"rounding_decimal_places", "max_discount_percent"} <= fields
