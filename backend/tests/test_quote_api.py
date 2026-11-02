import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.session import get_session
from app.db.tenant import set_tenant_context
from app.main import app
from app.models.pricing import PriceList, PriceTier
from app.models.product import Product
from app.models.quote import ApprovalTask
from app.models.tenant import Tenant, TenantMembership, User

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

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


def _headers(tenant: Tenant, user: User) -> dict[str, str]:
    return {"X-Tenant-Id": str(tenant.id), "X-User-Id": str(user.id)}


async def seed_api(session: AsyncSession, slug: str) -> ApiSeed:
    tenant = Tenant(name=slug, slug=slug)
    session.add(tenant)
    await session.flush()
    await set_tenant_context(session, tenant.id)

    requester = User(email=f"rep@{slug}.example", password_hash="x", display_name="Sales Rep")
    approver = User(email=f"approver@{slug}.example", password_hash="x", display_name="Approver")
    outsider = User(email=f"outsider@{slug}.example", password_hash="x", display_name="Outsider")
    session.add_all([requester, approver, outsider])
    await session.flush()
    session.add_all(
        [
            TenantMembership(tenant_id=tenant.id, user_id=requester.id, role_code="SALES_REP"),
            TenantMembership(tenant_id=tenant.id, user_id=approver.id, role_code="APPROVER"),
        ]
    )

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
        requester_headers=_headers(tenant, requester),
        approver_headers=_headers(tenant, approver),
        outsider_headers=_headers(tenant, outsider),
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


async def test_quote_request_requires_identity_headers(client: AsyncClient) -> None:
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
