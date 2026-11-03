import os
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.db.session import get_session
from app.db.tenant import set_tenant_context
from app.main import app
from app.models.audit import AuditLog
from app.models.customer import Customer
from app.models.inquiry import Inquiry, InquiryRequirement
from app.models.matching import ProductMatch
from app.models.product import Product
from app.models.tenant import Tenant, TenantMembership, User

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
PASSWORD_HASH = hash_password("test-password")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to run database integration tests",
)

FULL_CONFIRMED = {
    "product_category": "BOLT",
    "standard_code": "DIN 933",
    "material": "SS304",
    "grade": "8.8",
    "diameter": "M8",
    "length": "50mm",
    "surface_finish": "PLAIN",
    "quantity": "5000",
    "unit": "PCS",
}


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
class MatchingSeed:
    tenant: Tenant
    rep: User
    viewer: User
    customer: Customer
    products: dict[str, Product]
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


def _product(tenant_id: uuid.UUID, code: str, **overrides: Any) -> Product:
    values: dict[str, Any] = {
        "tenant_id": tenant_id,
        "product_code": code,
        "product_name": f"Hex bolt {code}",
        "category": "BOLT",
        "standard_code": "DIN 933",
        "material": "SS304",
        "grade": "8.8",
        "diameter": "M8",
        "length": "50mm",
        "surface_finish": "PLAIN",
        "sales_unit": "PCS",
        "moq": Decimal("1000"),
        "status": "ACTIVE",
    }
    values.update(overrides)
    return Product(**values)


async def seed_matching(session: AsyncSession, slug: str) -> MatchingSeed:
    tenant = Tenant(name=slug, slug=slug)
    other_tenant = Tenant(name=f"{slug}-other", slug=f"{slug}-other")
    session.add_all([tenant, other_tenant])
    await session.flush()

    rep = User(email=f"rep@{slug}.example", password_hash=PASSWORD_HASH, display_name="Rep")
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

    products = {
        "exact": _product(tenant.id, "BOLT-EXACT"),
        "other_material": _product(tenant.id, "BOLT-SS316", material="SS316"),
        "other_diameter": _product(tenant.id, "BOLT-M10", diameter="M10"),
        "other_finish": _product(tenant.id, "BOLT-HDG", length="60mm", surface_finish="HDG"),
        "nut": _product(tenant.id, "NUT-M8", category="NUT", product_name="Hex nut M8"),
        "sparse": _product(
            tenant.id,
            "BOLT-SPARSE",
            standard_code=None,
            grade=None,
            length=None,
            surface_finish=None,
            moq=Decimal("10000"),
        ),
        "inactive": _product(tenant.id, "BOLT-INACTIVE", status="INACTIVE"),
    }
    session.add_all(products.values())
    await session.flush()

    await set_tenant_context(session, other_tenant.id)
    other_customer = Customer(tenant_id=other_tenant.id, company_name="Other Buyer")
    session.add(other_customer)
    await session.flush()
    other_inquiry = Inquiry(
        tenant_id=other_tenant.id,
        customer_id=other_customer.id,
        subject="Other tenant RFQ",
        source_type="MANUAL",
        status="READY_FOR_MATCH",
    )
    session.add(other_inquiry)
    await session.flush()

    await set_tenant_context(session, tenant.id)
    return MatchingSeed(
        tenant=tenant,
        rep=rep,
        viewer=viewer,
        customer=customer,
        products=products,
        other_inquiry=other_inquiry,
        rep_headers=_bearer(tenant, rep, rep_membership.id),
        viewer_headers=_bearer(tenant, viewer, viewer_membership.id),
    )


async def create_inquiry(client: AsyncClient, seed: MatchingSeed) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/inquiries",
        json={
            "customer_id": str(seed.customer.id),
            "subject": "RFQ - fasteners",
            "source_type": "MANUAL",
            "raw_body": "We need 5000 pcs of SS304 M8 x 50mm hex bolts.",
            "language": "en",
        },
        headers=seed.rep_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def create_requirement(
    session: AsyncSession,
    seed: MatchingSeed,
    inquiry_id: str | uuid.UUID,
    *,
    parsed: dict[str, Any] | None = None,
    confirmed: dict[str, Any] | None = None,
    schema_version: int = 1,
) -> InquiryRequirement:
    await set_tenant_context(session, seed.tenant.id)
    requirement = InquiryRequirement(
        tenant_id=seed.tenant.id,
        inquiry_id=uuid.UUID(str(inquiry_id)),
        schema_version=schema_version,
        parsed_json=parsed or {},
        confirmed_json=confirmed or {},
    )
    session.add(requirement)
    await session.flush()
    return requirement


async def prepare_ready_inquiry(
    client: AsyncClient,
    seed: MatchingSeed,
    *,
    confirmed: dict[str, Any] | None = None,
    status: str = "READY_FOR_MATCH",
) -> dict[str, Any]:
    inquiry = await create_inquiry(client, seed)
    if confirmed is not None:
        response = await client.patch(
            f"/api/v1/inquiries/{inquiry['id']}/requirements",
            json={"schema_version": 1, "confirmed": confirmed},
            headers=seed.rep_headers,
        )
        assert response.status_code == 200, response.text
    moved = await client.patch(
        f"/api/v1/inquiries/{inquiry['id']}",
        json={"status": status},
        headers=seed.rep_headers,
    )
    assert moved.status_code == 200, moved.text
    return moved.json()["data"]


def matches_by_code(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {match["product_code"]: match for match in payload["matches"]}


async def test_generate_matches_ranks_candidates(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_matching(session, "match-rank")
    inquiry = await prepare_ready_inquiry(client, seed, confirmed=FULL_CONFIRMED)

    response = await client.post(
        f"/api/v1/inquiries/{inquiry['id']}/matches",
        headers=seed.rep_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["inquiry_id"] == inquiry["id"]
    assert data["inquiry_status"] == "MATCHED"
    assert data["schema_version"] == 1
    by_code = matches_by_code(data)

    assert "NUT-M8" not in by_code
    assert "BOLT-INACTIVE" not in by_code
    assert data["matches"][0]["product_code"] == "BOLT-EXACT"
    assert data["matches"][0]["match_status"] == "EXACT"
    assert data["matches"][0]["score"] == "1.0000"
    assert set(data["matches"][0]["matched_fields"]) == {
        "standard_code",
        "material",
        "grade",
        "diameter",
        "length",
        "surface_finish",
    }

    assert by_code["BOLT-SS316"]["match_status"] == "CONFLICT"
    assert by_code["BOLT-SS316"]["conflict_fields"] == ["material"]
    assert by_code["BOLT-M10"]["conflict_fields"] == ["diameter"]
    assert set(by_code["BOLT-HDG"]["conflict_fields"]) == {"length", "surface_finish"}
    assert by_code["BOLT-SPARSE"]["match_status"] == "NO_MATCH"
    assert set(by_code["BOLT-SPARSE"]["unknown_fields"]) == {
        "standard_code",
        "grade",
        "length",
        "surface_finish",
    }

    statuses = [match["match_status"] for match in data["matches"]]
    assert statuses[0] == "EXACT"
    assert statuses.index("CONFLICT") < statuses.index("NO_MATCH")

    stored = await client.get(
        f"/api/v1/inquiries/{inquiry['id']}/matches",
        headers=seed.rep_headers,
    )
    assert stored.status_code == 200, stored.text
    assert stored.json()["data"]["matches"] == data["matches"]

    await set_tenant_context(session, seed.tenant.id)
    entries = list(
        await session.scalars(
            select(AuditLog).where(
                AuditLog.tenant_id == seed.tenant.id,
                AuditLog.resource_type == "INQUIRY",
                AuditLog.resource_id == uuid.UUID(inquiry["id"]),
            )
        )
    )
    generate_events = [entry for entry in entries if entry.action == "inquiry.matches.generate"]
    assert len(generate_events) == 1
    assert generate_events[0].metadata_json["candidate_count"] == len(data["matches"])


async def test_confirmed_values_override_parsed_values(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_matching(session, "match-confirmed")
    inquiry = await create_inquiry(client, seed)
    await create_requirement(
        session,
        seed,
        inquiry["id"],
        parsed={
            "product_category": {"normalized_value": "BOLT", "confidence": 0.9},
            "standard_code": {"normalized_value": "DIN 933", "confidence": 0.9},
            "material": {"normalized_value": "SS304", "confidence": 0.9},
            "grade": {"normalized_value": "8.8", "confidence": 0.9},
            "diameter": {"normalized_value": "M8", "confidence": 0.9},
            "length": {"normalized_value": "50mm", "confidence": 0.9},
            "surface_finish": {"normalized_value": "PLAIN", "confidence": 0.9},
            "quantity": {"normalized_value": "5000", "confidence": 0.9},
            "unit": "PCS",
        },
    )
    await client.patch(
        f"/api/v1/inquiries/{inquiry['id']}",
        json={"status": "READY_FOR_MATCH"},
        headers=seed.rep_headers,
    )
    corrected = await client.patch(
        f"/api/v1/inquiries/{inquiry['id']}/requirements",
        json={"schema_version": 1, "confirmed": {"material": "SS316"}},
        headers=seed.rep_headers,
    )
    assert corrected.status_code == 200, corrected.text

    response = await client.post(
        f"/api/v1/inquiries/{inquiry['id']}/matches",
        headers=seed.rep_headers,
    )

    assert response.status_code == 200, response.text
    by_code = matches_by_code(response.json()["data"])
    assert by_code["BOLT-SS316"]["match_status"] == "EXACT"
    assert by_code["BOLT-EXACT"]["match_status"] == "CONFLICT"
    assert by_code["BOLT-EXACT"]["conflict_fields"] == ["material"]


async def test_moq_shortfall_is_explained_without_blocking_match(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_matching(session, "match-moq")
    inquiry = await prepare_ready_inquiry(
        client, seed, confirmed={**FULL_CONFIRMED, "quantity": "500"}
    )

    response = await client.post(
        f"/api/v1/inquiries/{inquiry['id']}/matches",
        headers=seed.rep_headers,
    )

    assert response.status_code == 200, response.text
    exact = matches_by_code(response.json()["data"])["BOLT-EXACT"]
    assert exact["match_status"] == "EXACT"
    assert "below MOQ" in exact["explanation"]
    assert "special approval" in exact["explanation"]


async def test_generate_without_candidates_keeps_inquiry_ready(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_matching(session, "match-empty")
    inquiry = await prepare_ready_inquiry(
        client, seed, confirmed={**FULL_CONFIRMED, "product_category": "WASHER"}
    )

    response = await client.post(
        f"/api/v1/inquiries/{inquiry['id']}/matches",
        headers=seed.rep_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["matches"] == []
    assert data["inquiry_status"] == "READY_FOR_MATCH"


async def test_generate_requires_matchable_status(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_matching(session, "match-status")
    inquiry = await prepare_ready_inquiry(client, seed, confirmed=FULL_CONFIRMED, status="RECEIVED")

    response = await client.post(
        f"/api/v1/inquiries/{inquiry['id']}/matches",
        headers=seed.rep_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INQUIRY_STATUS_NOT_MATCHABLE"


async def test_generate_requires_parsed_requirements(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_matching(session, "match-noreq")
    inquiry = await prepare_ready_inquiry(client, seed)

    response = await client.post(
        f"/api/v1/inquiries/{inquiry['id']}/matches",
        headers=seed.rep_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REQUIREMENTS_NOT_READY"


async def test_generate_requires_product_category(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_matching(session, "match-nocategory")
    inquiry = await create_inquiry(client, seed)
    await create_requirement(
        session,
        seed,
        inquiry["id"],
        parsed={"material": {"normalized_value": "SS304", "confidence": 0.9}},
    )
    await client.patch(
        f"/api/v1/inquiries/{inquiry['id']}",
        json={"status": "READY_FOR_MATCH"},
        headers=seed.rep_headers,
    )

    response = await client.post(
        f"/api/v1/inquiries/{inquiry['id']}/matches",
        headers=seed.rep_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REQUIREMENTS_INCOMPLETE"


async def test_get_matches_without_requirements_returns_empty(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_matching(session, "match-get-empty")
    inquiry = await create_inquiry(client, seed)

    response = await client.get(
        f"/api/v1/inquiries/{inquiry['id']}/matches",
        headers=seed.rep_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["schema_version"] is None
    assert data["matches"] == []
    assert data["inquiry_status"] == "RECEIVED"


async def test_regenerate_replaces_previous_matches(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_matching(session, "match-replace")
    inquiry = await prepare_ready_inquiry(client, seed, confirmed=FULL_CONFIRMED)

    first = await client.post(
        f"/api/v1/inquiries/{inquiry['id']}/matches",
        headers=seed.rep_headers,
    )
    second = await client.post(
        f"/api/v1/inquiries/{inquiry['id']}/matches",
        headers=seed.rep_headers,
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert len(first.json()["data"]["matches"]) == len(second.json()["data"]["matches"])
    await set_tenant_context(session, seed.tenant.id)
    count = await session.scalar(
        select(func.count())
        .select_from(ProductMatch)
        .where(
            ProductMatch.tenant_id == seed.tenant.id,
            ProductMatch.inquiry_id == uuid.UUID(inquiry["id"]),
        )
    )
    assert count == len(second.json()["data"]["matches"])


async def test_matches_are_scoped_to_tenant(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_matching(session, "match-isolation")

    read = await client.get(
        f"/api/v1/inquiries/{seed.other_inquiry.id}/matches",
        headers=seed.rep_headers,
    )
    generate = await client.post(
        f"/api/v1/inquiries/{seed.other_inquiry.id}/matches",
        headers=seed.rep_headers,
    )

    assert read.status_code == 404
    assert generate.status_code == 404
    assert generate.json()["error"]["code"] == "INQUIRY_NOT_FOUND"


async def test_viewer_can_read_but_not_generate_matches(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_matching(session, "match-rbac")
    inquiry = await prepare_ready_inquiry(client, seed, confirmed=FULL_CONFIRMED)
    await client.post(
        f"/api/v1/inquiries/{inquiry['id']}/matches",
        headers=seed.rep_headers,
    )

    read = await client.get(
        f"/api/v1/inquiries/{inquiry['id']}/matches",
        headers=seed.viewer_headers,
    )
    denied = await client.post(
        f"/api/v1/inquiries/{inquiry['id']}/matches",
        headers=seed.viewer_headers,
    )

    assert read.status_code == 200
    assert denied.status_code == 403
    assert denied.json()["error"]["details"] == [{"permission": "ai:run", "role": "VIEWER"}]
