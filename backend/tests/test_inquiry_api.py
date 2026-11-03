import os
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.db.session import get_session
from app.db.tenant import set_tenant_context
from app.main import app
from app.models.customer import Customer
from app.models.inquiry import Inquiry
from app.models.pricing import PriceList, PriceTier
from app.models.product import Product
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
class InquirySeed:
    tenant: Tenant
    rep: User
    viewer: User
    customer: Customer
    other_tenant: Tenant
    other_customer: Customer
    other_inquiry: Inquiry
    product: Product
    rep_headers: dict[str, str]
    viewer_headers: dict[str, str]


def _bearer(tenant: Tenant, user: User, membership_id: uuid.UUID) -> dict[str, str]:
    token = create_access_token(
        user_id=user.id,
        tenant_id=tenant.id,
        membership_id=membership_id,
    )
    return {"Authorization": f"Bearer {token}"}


async def seed_inquiries(session: AsyncSession, slug: str) -> InquirySeed:
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
    await session.flush()

    customer = Customer(tenant_id=tenant.id, company_name="Fastener Buyer GmbH")
    product = Product(
        tenant_id=tenant.id,
        product_code="BOLT-M8-50",
        product_name="Hex bolt M8x50 SS304",
        category="BOLT",
        sales_unit="PCS",
        moq=Decimal("1000"),
    )
    price_list = PriceList(
        tenant_id=tenant.id,
        name="2026 USD",
        currency="USD",
        valid_from=date(2026, 1, 1),
        status="ACTIVE",
        version=1,
    )
    session.add_all([customer, product, price_list])
    await session.flush()
    session.add(
        PriceTier(
            tenant_id=tenant.id,
            price_list_id=price_list.id,
            product_id=product.id,
            min_quantity=Decimal("1"),
            unit_price=Decimal("2.5000"),
            price_basis="PER_PIECE",
            unit="PCS",
        )
    )
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
    return InquirySeed(
        tenant=tenant,
        rep=rep,
        viewer=viewer,
        customer=customer,
        other_tenant=other_tenant,
        other_customer=other_customer,
        other_inquiry=other_inquiry,
        product=product,
        rep_headers=_bearer(tenant, rep, rep_membership.id),
        viewer_headers=_bearer(tenant, viewer, viewer_membership.id),
    )


def inquiry_payload(seed: InquirySeed, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "customer_id": str(seed.customer.id),
        "subject": "RFQ - stainless steel bolts",
        "source_type": "MANUAL",
        "raw_body": "We need 5000 pcs of SS304 M8 x 50mm hex bolts.",
        "language": "en",
        "received_at": "2026-10-30T02:00:00Z",
    }
    payload.update(overrides)
    return payload


async def create_inquiry(
    client: AsyncClient, seed: InquirySeed, **overrides: Any
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/inquiries",
        json=inquiry_payload(seed, **overrides),
        headers=seed.rep_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_create_inquiry_defaults_owner_and_status(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_inquiries(session, "inq-create")

    response = await client.post(
        "/api/v1/inquiries",
        json=inquiry_payload(seed),
        headers={**seed.rep_headers, "X-Request-ID": "req_inq_create"},
    )

    assert response.status_code == 201
    assert response.headers["X-Request-ID"] == "req_inq_create"
    body = response.json()
    assert body["meta"]["request_id"] == "req_inq_create"
    data = body["data"]
    assert data["status"] == "RECEIVED"
    assert data["source_type"] == "MANUAL"
    assert data["owner_user_id"] == str(seed.rep.id)
    assert data["subject"] == "RFQ - stainless steel bolts"
    assert data["raw_body"] == "We need 5000 pcs of SS304 M8 x 50mm hex bolts."
    assert data["received_at"] == "2026-10-30T02:00:00Z"


async def test_inquiry_requires_bearer_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/inquiries")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


async def test_list_inquiries_filters_and_paginates(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_inquiries(session, "inq-list")
    first = await create_inquiry(
        client, seed, subject="RFQ bolts", received_at="2026-10-30T02:00:00Z"
    )
    second = await create_inquiry(
        client, seed, subject="RFQ nuts", received_at="2026-10-31T02:00:00Z"
    )

    response = await client.get(
        "/api/v1/inquiries",
        params={"page": 1, "page_size": 1},
        headers=seed.rep_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["page"] == 1
    assert body["meta"]["page_size"] == 1
    assert body["meta"]["total"] == 2
    assert len(body["data"]) == 1
    assert body["data"][0]["id"] == second["id"]
    assert body["data"][0]["id"] != first["id"]

    filtered = await client.get(
        "/api/v1/inquiries",
        params={
            "status": "RECEIVED",
            "customer_id": str(seed.customer.id),
            "q": "nuts",
        },
        headers=seed.rep_headers,
    )
    assert filtered.status_code == 200
    assert filtered.json()["meta"]["total"] == 1
    assert filtered.json()["data"][0]["subject"] == "RFQ nuts"


async def test_get_and_update_inquiry(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_inquiries(session, "inq-update")
    created = await create_inquiry(client, seed)

    detail = await client.get(f"/api/v1/inquiries/{created['id']}", headers=seed.rep_headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["source_ref"] is None

    updated = await client.patch(
        f"/api/v1/inquiries/{created['id']}",
        json={
            "subject": "RFQ - updated",
            "status": "READY_FOR_MATCH",
            "source_ref": "EMAIL-42",
            "language": "de",
        },
        headers=seed.rep_headers,
    )
    assert updated.status_code == 200, updated.text
    data = updated.json()["data"]
    assert data["subject"] == "RFQ - updated"
    assert data["status"] == "READY_FOR_MATCH"
    assert data["source_ref"] == "EMAIL-42"
    assert data["language"] == "de"
    assert data["owner_user_id"] == str(seed.rep.id)


async def test_update_inquiry_rejects_invalid_status_transition(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_inquiries(session, "inq-status")
    created = await create_inquiry(client, seed)

    response = await client.patch(
        f"/api/v1/inquiries/{created['id']}",
        json={"status": "WON"},
        headers=seed.rep_headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


async def test_update_inquiry_rejects_null_required_fields(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_inquiries(session, "inq-null")
    created = await create_inquiry(client, seed)

    response = await client.patch(
        f"/api/v1/inquiries/{created['id']}",
        json={"subject": None},
        headers=seed.rep_headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_create_inquiry_validates_customer_and_owner(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_inquiries(session, "inq-refs")

    unknown_customer = await client.post(
        "/api/v1/inquiries",
        json=inquiry_payload(seed, customer_id=str(uuid.uuid4())),
        headers=seed.rep_headers,
    )
    assert unknown_customer.status_code == 404
    assert unknown_customer.json()["error"]["code"] == "CUSTOMER_NOT_FOUND"

    cross_tenant_customer = await client.post(
        "/api/v1/inquiries",
        json=inquiry_payload(seed, customer_id=str(seed.other_customer.id)),
        headers=seed.rep_headers,
    )
    assert cross_tenant_customer.status_code == 404
    assert cross_tenant_customer.json()["error"]["code"] == "CUSTOMER_NOT_FOUND"

    foreign_owner = await client.post(
        "/api/v1/inquiries",
        json=inquiry_payload(seed, owner_user_id=str(uuid.uuid4())),
        headers=seed.rep_headers,
    )
    assert foreign_owner.status_code == 400
    assert foreign_owner.json()["error"]["code"] == "OWNER_NOT_MEMBER"


async def test_inquiry_is_isolated_per_tenant(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_inquiries(session, "inq-isolation")

    response = await client.get(
        f"/api/v1/inquiries/{seed.other_inquiry.id}",
        headers=seed.rep_headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INQUIRY_NOT_FOUND"


async def test_requirements_upsert_and_latest_version(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_inquiries(session, "inq-requirements")
    created = await create_inquiry(client, seed)

    empty = await client.get(
        f"/api/v1/inquiries/{created['id']}/requirements",
        headers=seed.rep_headers,
    )
    assert empty.status_code == 200
    assert empty.json()["data"] is None

    first = await client.patch(
        f"/api/v1/inquiries/{created['id']}/requirements",
        json={
            "schema_version": 1,
            "confirmed": {"material": "SS304", "quantity": "5000"},
        },
        headers=seed.rep_headers,
    )
    assert first.status_code == 200, first.text
    assert first.json()["data"]["schema_version"] == 1
    assert first.json()["data"]["confirmed"] == {"material": "SS304", "quantity": "5000"}
    assert first.json()["data"]["parsed"] == {}

    second = await client.patch(
        f"/api/v1/inquiries/{created['id']}/requirements",
        json={"schema_version": 2, "confirmed": {"material": "SS316"}},
        headers=seed.rep_headers,
    )
    assert second.status_code == 200
    assert second.json()["data"]["schema_version"] == 2

    latest = await client.get(
        f"/api/v1/inquiries/{created['id']}/requirements",
        headers=seed.rep_headers,
    )
    assert latest.json()["data"]["schema_version"] == 2
    assert latest.json()["data"]["confirmed"] == {"material": "SS316"}


async def test_viewer_can_read_but_not_create_inquiries(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_inquiries(session, "inq-rbac")
    await create_inquiry(client, seed)

    listed = await client.get("/api/v1/inquiries", headers=seed.viewer_headers)
    assert listed.status_code == 200

    denied = await client.post(
        "/api/v1/inquiries",
        json=inquiry_payload(seed),
        headers=seed.viewer_headers,
    )
    assert denied.status_code == 403
    error = denied.json()["error"]
    assert error["code"] == "PERMISSION_DENIED"
    assert error["details"] == [{"permission": "inquiry:create", "role": "VIEWER"}]


async def test_quote_persists_inquiry_link(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_inquiries(session, "inq-quote")
    created = await create_inquiry(client, seed)

    response = await client.post(
        "/api/v1/quotes",
        json={
            "inquiry_id": created["id"],
            "currency": "USD",
            "items": [
                {
                    "product_id": str(seed.product.id),
                    "quantity": "1000",
                    "unit": "PCS",
                }
            ],
            "valid_until": "2026-12-31",
        },
        headers=seed.rep_headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["data"]["inquiry_id"] == created["id"]


async def test_quote_rejects_unknown_or_foreign_inquiry(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_inquiries(session, "inq-quote-404")
    payload = {
        "currency": "USD",
        "items": [
            {
                "product_id": str(seed.product.id),
                "quantity": "1000",
                "unit": "PCS",
            }
        ],
    }

    unknown = await client.post(
        "/api/v1/quotes",
        json={**payload, "inquiry_id": str(uuid.uuid4())},
        headers=seed.rep_headers,
    )
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "INQUIRY_NOT_FOUND"

    foreign = await client.post(
        "/api/v1/quotes",
        json={**payload, "inquiry_id": str(seed.other_inquiry.id)},
        headers=seed.rep_headers,
    )
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "INQUIRY_NOT_FOUND"
