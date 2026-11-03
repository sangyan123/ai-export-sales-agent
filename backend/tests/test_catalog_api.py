import os
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.session import get_session
from app.db.tenant import set_tenant_context
from app.main import app
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
class Account:
    tenant: Tenant
    user: User
    headers: dict[str, str]


async def seed_account(session: AsyncSession, slug: str) -> Account:
    tenant = Tenant(name=slug, slug=slug)
    session.add(tenant)
    await session.flush()
    await set_tenant_context(session, tenant.id)

    user = User(email=f"user@{slug}.example", password_hash="x", display_name="Sales Rep")
    session.add(user)
    await session.flush()
    session.add(TenantMembership(tenant_id=tenant.id, user_id=user.id, role_code="SALES_REP"))
    await session.flush()
    return Account(
        tenant=tenant,
        user=user,
        headers={"X-Tenant-Id": str(tenant.id), "X-User-Id": str(user.id)},
    )


def product_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "product_code": "BOLT-M8-30",
        "product_name": "Hex bolt M8x30 SS304",
        "category": "BOLT",
        "material": "SS304",
        "diameter": "M8",
        "length": "30mm",
        "sales_unit": "PCS",
        "moq": "1000",
        "attributes": {"thread": "full"},
    }
    payload.update(overrides)
    return payload


async def create_product(client: AsyncClient, account: Account, **overrides: Any) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/products", json=product_payload(**overrides), headers=account.headers
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def price_list_payload(product_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "2026 USD",
        "currency": "usd",
        "valid_from": "2026-01-01",
        "tiers": [
            {
                "product_id": product_id,
                "min_quantity": "1",
                "max_quantity": "999",
                "unit_price": "2.5000",
                "price_basis": "PER_PIECE",
                "unit": "PCS",
            },
            {
                "product_id": product_id,
                "min_quantity": "1000",
                "unit_price": "2.2000",
                "price_basis": "PER_PIECE",
                "unit": "PCS",
            },
        ],
    }
    payload.update(overrides)
    return payload


async def create_price_list(
    client: AsyncClient, account: Account, product_id: str, **overrides: Any
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/price-lists",
        json=price_list_payload(product_id, **overrides),
        headers=account.headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def customer_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "company_name": "Acme Fasteners GmbH",
        "country_code": "de",
        "website": "https://acme.example",
        "source": "REFERRAL",
    }
    payload.update(overrides)
    return payload


async def create_customer(
    client: AsyncClient, account: Account, **overrides: Any
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/customers", json=customer_payload(**overrides), headers=account.headers
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def override_payload(product_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "product_id": product_id,
        "currency": "USD",
        "unit_price": "1.5000",
        "price_basis": "PER_PIECE",
        "unit": "PCS",
        "valid_from": "2026-01-01",
    }
    payload.update(overrides)
    return payload


async def create_override(
    client: AsyncClient,
    account: Account,
    customer_id: str,
    product_id: str,
    **overrides: Any,
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/customers/{customer_id}/price-overrides",
        json=override_payload(product_id, **overrides),
        headers=account.headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_product_crud_and_search(client: AsyncClient, session: AsyncSession) -> None:
    account = await seed_account(session, "catalog-product")

    created = await create_product(client, account)
    assert created["category"] == "BOLT"
    assert created["status"] == "ACTIVE"
    assert created["moq"] == "1000.0000"
    assert created["attributes"] == {"thread": "full"}

    await create_product(
        client,
        account,
        product_code="NUT-M8",
        product_name="Hex nut M8 SS304",
        category="NUT",
        moq=None,
        attributes={},
    )

    searched = await client.get("/api/v1/products", params={"q": "BOLT"}, headers=account.headers)
    assert searched.status_code == 200
    assert searched.json()["meta"]["total"] == 1
    assert searched.json()["data"][0]["product_code"] == "BOLT-M8-30"

    detail = await client.get(f"/api/v1/products/{created['id']}", headers=account.headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["material"] == "SS304"

    updated = await client.patch(
        f"/api/v1/products/{created['id']}",
        json={"moq": "500", "status": "INACTIVE", "grade": "A2-70"},
        headers=account.headers,
    )
    assert updated.status_code == 200
    data = updated.json()["data"]
    assert data["moq"] == "500.0000"
    assert data["status"] == "INACTIVE"
    assert data["grade"] == "A2-70"

    filtered = await client.get(
        "/api/v1/products",
        params={"category": "BOLT", "status": "INACTIVE"},
        headers=account.headers,
    )
    assert filtered.json()["meta"]["total"] == 1


async def test_product_duplicate_code_conflict(client: AsyncClient, session: AsyncSession) -> None:
    account = await seed_account(session, "catalog-product-dup")
    await create_product(client, account)

    response = await client.post(
        "/api/v1/products", json=product_payload(), headers=account.headers
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PRODUCT_CODE_EXISTS"


async def test_product_validation_error_uses_envelope(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await seed_account(session, "catalog-product-invalid")

    response = await client.post(
        "/api/v1/products",
        json=product_payload(category="SPRING"),
        headers=account.headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_product_is_not_visible_to_another_tenant(
    client: AsyncClient, session: AsyncSession
) -> None:
    account_a = await seed_account(session, "catalog-product-a")
    account_b = await seed_account(session, "catalog-product-b")
    created = await create_product(client, account_a)

    response = await client.get(f"/api/v1/products/{created['id']}", headers=account_b.headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PRODUCT_NOT_FOUND"


async def test_price_list_crud_with_tiers(client: AsyncClient, session: AsyncSession) -> None:
    account = await seed_account(session, "catalog-price-list")
    product = await create_product(client, account)

    created = await create_price_list(client, account, product["id"])
    assert created["currency"] == "USD"
    assert len(created["tiers"]) == 2
    first_tier = created["tiers"][0]
    assert first_tier["min_quantity"] == "1.0000"
    assert first_tier["max_quantity"] == "999.0000"
    assert first_tier["unit_price"] == "2.5000"

    listed = await client.get(
        "/api/v1/price-lists", params={"currency": "usd"}, headers=account.headers
    )
    assert listed.status_code == 200
    assert listed.json()["meta"]["total"] == 1

    updated_tier = await client.patch(
        f"/api/v1/price-tiers/{first_tier['id']}",
        json={"unit_price": "2.4500", "max_quantity": "998"},
        headers=account.headers,
    )
    assert updated_tier.status_code == 200
    assert updated_tier.json()["data"]["unit_price"] == "2.4500"

    archived = await client.patch(
        f"/api/v1/price-lists/{created['id']}",
        json={"status": "INACTIVE"},
        headers=account.headers,
    )
    assert archived.status_code == 200
    assert archived.json()["data"]["status"] == "INACTIVE"
    assert len(archived.json()["data"]["tiers"]) == 2


async def test_price_tier_overlap_is_rejected(client: AsyncClient, session: AsyncSession) -> None:
    account = await seed_account(session, "catalog-tier-overlap")
    product = await create_product(client, account)
    price_list = await create_price_list(
        client,
        account,
        product["id"],
        tiers=[
            {
                "product_id": product["id"],
                "min_quantity": "1",
                "max_quantity": "999",
                "unit_price": "2.5000",
                "price_basis": "PER_PIECE",
                "unit": "PCS",
            }
        ],
    )

    overlap = await client.post(
        f"/api/v1/price-lists/{price_list['id']}/tiers",
        json={
            "product_id": product["id"],
            "min_quantity": "500",
            "max_quantity": "1500",
            "unit_price": "2.3000",
            "price_basis": "PER_PIECE",
            "unit": "PCS",
        },
        headers=account.headers,
    )
    assert overlap.status_code == 409
    assert overlap.json()["error"]["code"] == "PRICE_TIER_OVERLAP"

    adjacent = await client.post(
        f"/api/v1/price-lists/{price_list['id']}/tiers",
        json={
            "product_id": product["id"],
            "min_quantity": "1000",
            "unit_price": "2.2000",
            "price_basis": "PER_PIECE",
            "unit": "PCS",
        },
        headers=account.headers,
    )
    assert adjacent.status_code == 201
    assert adjacent.json()["data"]["min_quantity"] == "1000.0000"


async def test_price_list_rejects_product_from_another_tenant(
    client: AsyncClient, session: AsyncSession
) -> None:
    account_a = await seed_account(session, "catalog-price-a")
    account_b = await seed_account(session, "catalog-price-b")
    product_b = await create_product(client, account_b)

    response = await client.post(
        "/api/v1/price-lists",
        json=price_list_payload(product_b["id"]),
        headers=account_a.headers,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PRODUCT_NOT_FOUND"


async def test_customer_crud_and_search(client: AsyncClient, session: AsyncSession) -> None:
    account = await seed_account(session, "catalog-customer")

    created = await create_customer(client, account)
    assert created["company_name"] == "Acme Fasteners GmbH"
    assert created["country_code"] == "DE"
    assert created["status"] == "ACTIVE"

    searched = await client.get(
        "/api/v1/customers",
        params={"q": "Acme", "country_code": "de"},
        headers=account.headers,
    )
    assert searched.status_code == 200
    assert searched.json()["meta"]["total"] == 1

    updated = await client.patch(
        f"/api/v1/customers/{created['id']}",
        json={"website": "https://new.example", "status": "INACTIVE"},
        headers=account.headers,
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["website"] == "https://new.example"
    assert updated.json()["data"]["status"] == "INACTIVE"


async def test_customer_is_not_visible_to_another_tenant(
    client: AsyncClient, session: AsyncSession
) -> None:
    account_a = await seed_account(session, "catalog-customer-a")
    account_b = await seed_account(session, "catalog-customer-b")
    created = await create_customer(client, account_a)

    response = await client.get(f"/api/v1/customers/{created['id']}", headers=account_b.headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CUSTOMER_NOT_FOUND"


async def test_price_override_requires_approval_before_quoting(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await seed_account(session, "catalog-override-flow")
    product = await create_product(client, account)
    await create_price_list(client, account, product["id"])
    customer = await create_customer(client, account)
    override = await create_override(client, account, customer["id"], product["id"])

    assert override["approval_status"] == "PENDING"
    assert override["approved_by"] is None

    quote_payload = {
        "currency": "USD",
        "customer_id": customer["id"],
        "items": [{"product_id": product["id"], "quantity": "1000", "unit": "PCS"}],
    }
    before = await client.post("/api/v1/quotes", json=quote_payload, headers=account.headers)
    assert before.status_code == 201, before.text
    assert before.json()["data"]["grand_total"] == "2200.0000"
    assert before.json()["data"]["items"][0]["price_source_ref"]["kind"] == "PRICE_LIST"

    approved = await client.post(
        f"/api/v1/customers/{customer['id']}/price-overrides/{override['id']}/approve",
        headers=account.headers,
    )
    assert approved.status_code == 200
    assert approved.json()["data"]["approval_status"] == "APPROVED"
    assert approved.json()["data"]["approved_by"] == str(account.user.id)

    after = await client.post("/api/v1/quotes", json=quote_payload, headers=account.headers)
    assert after.status_code == 201, after.text
    data = after.json()["data"]
    assert data["grand_total"] == "1500.0000"
    assert data["items"][0]["price_source_ref"]["kind"] == "CUSTOMER_OVERRIDE"


async def test_price_override_overlap_and_immutability(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await seed_account(session, "catalog-override-rules")
    product = await create_product(client, account)
    customer = await create_customer(client, account)

    first = await create_override(
        client,
        account,
        customer["id"],
        product["id"],
        valid_from="2026-01-01",
        valid_to="2026-05-31",
    )
    first_approved = await client.post(
        f"/api/v1/customers/{customer['id']}/price-overrides/{first['id']}/approve",
        headers=account.headers,
    )
    assert first_approved.status_code == 200

    second = await create_override(
        client,
        account,
        customer["id"],
        product["id"],
        valid_from="2026-06-01",
        unit_price="1.6000",
    )
    second_approved = await client.post(
        f"/api/v1/customers/{customer['id']}/price-overrides/{second['id']}/approve",
        headers=account.headers,
    )
    assert second_approved.status_code == 200

    overlapping = await create_override(
        client,
        account,
        customer["id"],
        product["id"],
        valid_from="2026-03-01",
        valid_to="2026-06-30",
        unit_price="1.4000",
    )
    conflict = await client.post(
        f"/api/v1/customers/{customer['id']}/price-overrides/{overlapping['id']}/approve",
        headers=account.headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "PRICE_OVERRIDE_AMBIGUOUS"

    immutable = await client.patch(
        f"/api/v1/customers/{customer['id']}/price-overrides/{first['id']}",
        json={"unit_price": "1.0000"},
        headers=account.headers,
    )
    assert immutable.status_code == 409
    assert immutable.json()["error"]["code"] == "PRICE_OVERRIDE_NOT_PENDING"


async def test_price_override_duplicate_effective_date_conflicts(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await seed_account(session, "catalog-override-dup")
    product = await create_product(client, account)
    customer = await create_customer(client, account)
    await create_override(client, account, customer["id"], product["id"])

    response = await client.post(
        f"/api/v1/customers/{customer['id']}/price-overrides",
        json=override_payload(product["id"], unit_price="1.7000"),
        headers=account.headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PRICE_OVERRIDE_EXISTS"
