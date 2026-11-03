import os
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.ai import DeterministicInquiryParser, ParserError
from app.core.security import create_access_token, hash_password
from app.db.session import get_session
from app.db.tenant import set_tenant_context
from app.inquiries.analysis import InquiryAnalysisService
from app.main import app
from app.models.audit import AuditLog
from app.models.customer import Customer
from app.models.inquiry import Inquiry, InquiryRequirement
from app.models.tenant import Tenant, TenantMembership, User

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
PASSWORD_HASH = hash_password("test-password")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to run database integration tests",
)

FULL_RFQ = "We need 5000 pcs of SS304 M8 x 50mm hex bolts for Germany, FOB Shanghai."


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


@pytest.fixture
def scheduled(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_run(*, tenant_id: uuid.UUID, run_id: uuid.UUID) -> None:
        calls.append({"tenant_id": tenant_id, "run_id": run_id})

    monkeypatch.setattr("app.api.v1.inquiries.run_inquiry_analysis", fake_run)
    return calls


@dataclass(frozen=True)
class AnalysisSeed:
    tenant: Tenant
    rep: User
    viewer: User
    customer: Customer
    other_tenant: Tenant
    other_inquiry: Inquiry
    rep_headers: dict[str, str]
    viewer_headers: dict[str, str]


def _bearer(tenant: Tenant, user: User, membership_id: uuid.UUID) -> dict[str, str]:
    token = create_access_token(
        user_id=user.id,
        tenant_id=tenant.id,
        membership_id=membership_id,
    )
    return {"Authorization": f"Bearer {token}"}


async def seed_tenant(session: AsyncSession, slug: str) -> AnalysisSeed:
    tenant = Tenant(name=slug, slug=slug)
    other_tenant = Tenant(name=f"{slug}-other", slug=f"{slug}-other")
    session.add_all([tenant, other_tenant])
    await session.flush()

    rep = User(email=f"rep@{slug}.example", password_hash=PASSWORD_HASH, display_name="Sales Rep")
    viewer = User(
        email=f"viewer@{slug}.example", password_hash=PASSWORD_HASH, display_name="Viewer"
    )
    session.add_all([rep, viewer])
    await session.flush()

    await set_tenant_context(session, tenant.id)
    rep_membership = TenantMembership(tenant_id=tenant.id, user_id=rep.id, role_code="SALES_REP")
    viewer_membership = TenantMembership(tenant_id=tenant.id, user_id=viewer.id, role_code="VIEWER")
    session.add_all([rep_membership, viewer_membership])
    customer = Customer(tenant_id=tenant.id, company_name="Fastener Buyer GmbH")
    session.add(customer)
    await session.flush()

    await set_tenant_context(session, other_tenant.id)
    other_customer = Customer(tenant_id=other_tenant.id, company_name="Other Tenant Buyer")
    session.add(other_customer)
    await session.flush()
    other_inquiry = Inquiry(
        tenant_id=other_tenant.id,
        customer_id=other_customer.id,
        subject="Other tenant RFQ",
        source_type="MANUAL",
        status="RECEIVED",
    )
    session.add(other_inquiry)
    await session.flush()

    await set_tenant_context(session, tenant.id)
    return AnalysisSeed(
        tenant=tenant,
        rep=rep,
        viewer=viewer,
        customer=customer,
        other_tenant=other_tenant,
        other_inquiry=other_inquiry,
        rep_headers=_bearer(tenant, rep, rep_membership.id),
        viewer_headers=_bearer(tenant, viewer, viewer_membership.id),
    )


async def create_inquiry(
    client: AsyncClient,
    seed: AnalysisSeed,
    *,
    raw_body: str = FULL_RFQ,
    subject: str = "RFQ - stainless steel bolts",
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/inquiries",
        json={
            "customer_id": str(seed.customer.id),
            "subject": subject,
            "source_type": "MANUAL",
            "raw_body": raw_body,
            "language": "en",
        },
        headers=seed.rep_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def start_analysis(
    client: AsyncClient, seed: AnalysisSeed, inquiry_id: str
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/inquiries/{inquiry_id}/analysis",
        headers=seed.rep_headers,
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]


async def inquiry_status(client: AsyncClient, seed: AnalysisSeed, inquiry_id: str) -> str:
    response = await client.get(f"/api/v1/inquiries/{inquiry_id}", headers=seed.rep_headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]["status"]


async def inquiry_audit_entries(
    session: AsyncSession, seed: AnalysisSeed, inquiry_id: str
) -> list[AuditLog]:
    await set_tenant_context(session, seed.tenant.id)
    entries = await session.scalars(
        select(AuditLog)
        .where(
            AuditLog.tenant_id == seed.tenant.id,
            AuditLog.resource_type == "INQUIRY",
            AuditLog.resource_id == uuid.UUID(inquiry_id),
        )
        .order_by(AuditLog.created_at)
    )
    return list(entries)


async def test_create_analysis_enqueues_workflow_run(
    client: AsyncClient,
    session: AsyncSession,
    scheduled: list[dict[str, Any]],
) -> None:
    seed = await seed_tenant(session, "an-enqueue")
    inquiry = await create_inquiry(client, seed)

    response = await client.post(
        f"/api/v1/inquiries/{inquiry['id']}/analysis",
        headers=seed.rep_headers,
    )

    assert response.status_code == 202, response.text
    data = response.json()["data"]
    assert data["status"] == "QUEUED"
    assert data["inquiry_id"] == inquiry["id"]
    run_id = uuid.UUID(data["workflow_run_id"])
    assert scheduled == [{"tenant_id": seed.tenant.id, "run_id": run_id}]

    run = await client.get(f"/api/v1/workflow-runs/{run_id}", headers=seed.rep_headers)
    assert run.status_code == 200, run.text
    assert run.json()["data"]["workflow_type"] == "INQUIRY_ANALYSIS"
    assert run.json()["data"]["status"] == "QUEUED"
    assert await inquiry_status(client, seed, inquiry["id"]) == "PARSING"

    entries = await inquiry_audit_entries(session, seed, inquiry["id"])
    assert "inquiry.analysis.request" in [entry.action for entry in entries]


async def test_execute_analysis_persists_requirement_and_audit(
    client: AsyncClient,
    session: AsyncSession,
    scheduled: list[dict[str, Any]],
) -> None:
    seed = await seed_tenant(session, "an-success")
    inquiry = await create_inquiry(client, seed)
    data = await start_analysis(client, seed, inquiry["id"])

    service = InquiryAnalysisService(session, parser=DeterministicInquiryParser())
    run = await service.execute(
        tenant_id=seed.tenant.id,
        run_id=uuid.UUID(data["workflow_run_id"]),
    )

    assert run is not None
    assert run.status == "SUCCEEDED"
    assert run.finished_at is not None
    assert run.output_ref["schema_version"] == 1
    assert run.output_ref["critical_missing_fields"] == []

    requirements = await client.get(
        f"/api/v1/inquiries/{inquiry['id']}/requirements",
        headers=seed.rep_headers,
    )
    assert requirements.status_code == 200, requirements.text
    requirement = requirements.json()["data"]
    assert requirement["schema_version"] == 1
    assert requirement["confirmed"] == {}
    assert requirement["model_id"] == "deterministic-inquiry-parser.v1"
    assert requirement["parsed"]["product_category"]["normalized_value"] == "BOLT"
    assert requirement["parsed"]["material"]["normalized_value"] == "SS304"
    assert requirement["parsed"]["diameter"]["normalized_value"] == "M8"
    assert requirement["parsed"]["quantity"]["value"] == "5000"
    assert requirement["parsed"]["destination_country"]["normalized_value"] == "DE"
    assert requirement["confidence"]["diameter"] == 0.95
    assert "overall" in requirement["confidence"]
    assert requirement["evidence"]["material"] == "SS304"
    assert await inquiry_status(client, seed, inquiry["id"]) == "READY_FOR_MATCH"

    entries = {
        entry.action: entry for entry in await inquiry_audit_entries(session, seed, inquiry["id"])
    }
    completed = entries["inquiry.analysis.completed"]
    assert completed.metadata_json["workflow_run_id"] == data["workflow_run_id"]
    assert completed.metadata_json["schema_version"] == 1


async def test_execute_analysis_flags_missing_critical_fields(
    client: AsyncClient,
    session: AsyncSession,
    scheduled: list[dict[str, Any]],
) -> None:
    seed = await seed_tenant(session, "an-missing")
    inquiry = await create_inquiry(
        client, seed, raw_body="Please quote 5000 pcs of bolts.", subject="RFQ - fasteners"
    )
    data = await start_analysis(client, seed, inquiry["id"])

    service = InquiryAnalysisService(session, parser=DeterministicInquiryParser())
    run = await service.execute(
        tenant_id=seed.tenant.id,
        run_id=uuid.UUID(data["workflow_run_id"]),
    )

    assert run is not None
    assert run.status == "SUCCEEDED"
    assert set(run.output_ref["critical_missing_fields"]) == {"material", "diameter"}
    assert await inquiry_status(client, seed, inquiry["id"]) == "NEEDS_INFO"

    requirements = await client.get(
        f"/api/v1/inquiries/{inquiry['id']}/requirements",
        headers=seed.rep_headers,
    )
    parsed = requirements.json()["data"]["parsed"]
    assert "material" in parsed["missing_fields"]
    assert "diameter" in parsed["missing_fields"]


class FailingParser:
    model_id = "failing-parser.v1"

    async def parse(self, *, subject: str, raw_text: str, language: str | None):
        raise ParserError("PROVIDER_UNAVAILABLE", "provider is down")


async def test_execute_analysis_records_failure(
    client: AsyncClient,
    session: AsyncSession,
    scheduled: list[dict[str, Any]],
) -> None:
    seed = await seed_tenant(session, "an-failure")
    inquiry = await create_inquiry(client, seed)
    data = await start_analysis(client, seed, inquiry["id"])

    service = InquiryAnalysisService(session, parser=FailingParser())
    run = await service.execute(
        tenant_id=seed.tenant.id,
        run_id=uuid.UUID(data["workflow_run_id"]),
    )

    assert run is not None
    assert run.status == "FAILED"
    assert run.error_code == "PROVIDER_UNAVAILABLE"
    assert run.finished_at is not None
    assert await inquiry_status(client, seed, inquiry["id"]) == "NEEDS_INFO"

    requirements = await client.get(
        f"/api/v1/inquiries/{inquiry['id']}/requirements",
        headers=seed.rep_headers,
    )
    assert requirements.json()["data"] is None

    entries = await inquiry_audit_entries(session, seed, inquiry["id"])
    assert "inquiry.analysis.failed" in [entry.action for entry in entries]


async def test_cancelled_run_skips_parsing_and_restores_inquiry(
    client: AsyncClient,
    session: AsyncSession,
    scheduled: list[dict[str, Any]],
) -> None:
    seed = await seed_tenant(session, "an-cancel")
    inquiry = await create_inquiry(client, seed)
    data = await start_analysis(client, seed, inquiry["id"])

    cancelled = await client.post(
        f"/api/v1/workflow-runs/{data['workflow_run_id']}/cancel",
        headers=seed.rep_headers,
    )
    assert cancelled.status_code == 200, cancelled.text

    service = InquiryAnalysisService(session, parser=DeterministicInquiryParser())
    run = await service.execute(
        tenant_id=seed.tenant.id,
        run_id=uuid.UUID(data["workflow_run_id"]),
    )

    assert run is not None
    assert run.status == "CANCELLED"
    requirements = await client.get(
        f"/api/v1/inquiries/{inquiry['id']}/requirements",
        headers=seed.rep_headers,
    )
    assert requirements.json()["data"] is None
    assert await inquiry_status(client, seed, inquiry["id"]) == "NEEDS_INFO"


async def test_analysis_rejects_non_analyzable_status(
    client: AsyncClient,
    session: AsyncSession,
    scheduled: list[dict[str, Any]],
) -> None:
    seed = await seed_tenant(session, "an-status")
    inquiry = await create_inquiry(client, seed)
    moved = await client.patch(
        f"/api/v1/inquiries/{inquiry['id']}",
        json={"status": "READY_FOR_MATCH"},
        headers=seed.rep_headers,
    )
    assert moved.status_code == 200, moved.text

    response = await client.post(
        f"/api/v1/inquiries/{inquiry['id']}/analysis",
        headers=seed.rep_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INQUIRY_STATUS_NOT_ANALYZABLE"
    assert scheduled == []


async def test_analysis_rejects_concurrent_run(
    client: AsyncClient,
    session: AsyncSession,
    scheduled: list[dict[str, Any]],
) -> None:
    seed = await seed_tenant(session, "an-concurrent")
    inquiry = await create_inquiry(client, seed)
    await start_analysis(client, seed, inquiry["id"])

    response = await client.post(
        f"/api/v1/inquiries/{inquiry['id']}/analysis",
        headers=seed.rep_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INQUIRY_ANALYSIS_IN_PROGRESS"


async def test_analysis_requires_ai_run_permission(
    client: AsyncClient,
    session: AsyncSession,
    scheduled: list[dict[str, Any]],
) -> None:
    seed = await seed_tenant(session, "an-rbac")
    inquiry = await create_inquiry(client, seed)

    response = await client.post(
        f"/api/v1/inquiries/{inquiry['id']}/analysis",
        headers=seed.viewer_headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_analysis_is_scoped_to_tenant(
    client: AsyncClient,
    session: AsyncSession,
    scheduled: list[dict[str, Any]],
) -> None:
    seed = await seed_tenant(session, "an-isolation")

    response = await client.post(
        f"/api/v1/inquiries/{seed.other_inquiry.id}/analysis",
        headers=seed.rep_headers,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INQUIRY_NOT_FOUND"


async def test_reanalysis_creates_next_version_and_keeps_confirmed_values(
    client: AsyncClient,
    session: AsyncSession,
    scheduled: list[dict[str, Any]],
) -> None:
    seed = await seed_tenant(session, "an-version")
    inquiry = await create_inquiry(client, seed)
    service = InquiryAnalysisService(session, parser=DeterministicInquiryParser())

    first = await start_analysis(client, seed, inquiry["id"])
    await service.execute(tenant_id=seed.tenant.id, run_id=uuid.UUID(first["workflow_run_id"]))
    confirmed = await client.patch(
        f"/api/v1/inquiries/{inquiry['id']}/requirements",
        json={"schema_version": 1, "confirmed": {"material": "SS304"}},
        headers=seed.rep_headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    back = await client.patch(
        f"/api/v1/inquiries/{inquiry['id']}",
        json={"status": "NEEDS_INFO"},
        headers=seed.rep_headers,
    )
    assert back.status_code == 200, back.text

    second = await start_analysis(client, seed, inquiry["id"])
    await service.execute(tenant_id=seed.tenant.id, run_id=uuid.UUID(second["workflow_run_id"]))

    latest = await client.get(
        f"/api/v1/inquiries/{inquiry['id']}/requirements",
        headers=seed.rep_headers,
    )
    assert latest.json()["data"]["schema_version"] == 2
    assert latest.json()["data"]["confirmed"] == {}

    await set_tenant_context(session, seed.tenant.id)
    version_one = await session.scalar(
        select(InquiryRequirement).where(
            InquiryRequirement.tenant_id == seed.tenant.id,
            InquiryRequirement.inquiry_id == uuid.UUID(inquiry["id"]),
            InquiryRequirement.schema_version == 1,
        )
    )
    assert version_one is not None
    assert version_one.confirmed_json == {"material": "SS304"}
