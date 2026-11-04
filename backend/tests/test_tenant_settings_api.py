import os
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.db.session import get_session
from app.db.tenant import set_tenant_context
from app.main import app
from app.models.audit import AuditLog
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
class Account:
    tenant: Tenant
    user: User
    headers: dict[str, str]


async def seed_account(session: AsyncSession, slug: str, role_code: str = "OWNER") -> Account:
    tenant = Tenant(name=f"{slug} tenant", slug=slug)
    session.add(tenant)
    await session.flush()
    await set_tenant_context(session, tenant.id)

    user = User(email=f"user@{slug}.example", password_hash=PASSWORD_HASH, display_name="Owner")
    session.add(user)
    await session.flush()
    membership = TenantMembership(tenant_id=tenant.id, user_id=user.id, role_code=role_code)
    session.add(membership)
    await session.flush()
    token = create_access_token(
        user_id=user.id,
        tenant_id=tenant.id,
        membership_id=membership.id,
    )
    return Account(
        tenant=tenant,
        user=user,
        headers={"Authorization": f"Bearer {token}"},
    )


async def test_get_current_tenant_defaults(client: AsyncClient, session: AsyncSession) -> None:
    account = await seed_account(session, "acme")

    response = await client.get("/api/v1/tenants/current", headers=account.headers)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["id"] == str(account.tenant.id)
    assert data["name"] == "acme tenant"
    assert data["slug"] == "acme"
    assert data["status"] == "ACTIVE"
    assert data["plan_code"] is None
    assert data["contact_email"] is None
    assert data["contact_phone"] is None
    assert data["website"] is None
    assert data["address"] is None
    assert data["main_products"] is None
    assert data["export_markets"] == []
    assert data["default_currency"] == "USD"
    assert data["default_language"] == "en"
    assert data["created_at"]
    assert data["updated_at"]


async def test_update_tenant_profile(client: AsyncClient, session: AsyncSession) -> None:
    account = await seed_account(session, "acme")

    response = await client.patch(
        "/api/v1/tenants/current",
        headers=account.headers,
        json={
            "name": "  Acme Fasteners  ",
            "contact_email": " Sales@Acme.example ",
            "contact_phone": "+86 574 8888 0000",
            "website": "https://acme.example",
            "address": "Ningbo, Zhejiang, China",
            "main_products": "Hex bolts, nuts, washers",
            "export_markets": ["North America", " Europe ", "north america", ""],
            "default_currency": "eur",
            "default_language": "zh-CN",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["name"] == "Acme Fasteners"
    assert data["contact_email"] == "sales@acme.example"
    assert data["contact_phone"] == "+86 574 8888 0000"
    assert data["website"] == "https://acme.example"
    assert data["address"] == "Ningbo, Zhejiang, China"
    assert data["main_products"] == "Hex bolts, nuts, washers"
    assert data["export_markets"] == ["North America", "Europe"]
    assert data["default_currency"] == "EUR"
    assert data["default_language"] == "zh-cn"

    fetched = await client.get("/api/v1/tenants/current", headers=account.headers)
    assert fetched.status_code == 200
    stored = fetched.json()["data"]
    assert stored["name"] == "Acme Fasteners"
    assert stored["export_markets"] == ["North America", "Europe"]
    assert stored["default_currency"] == "EUR"
    assert stored["default_language"] == "zh-cn"


async def test_update_clears_optional_fields(client: AsyncClient, session: AsyncSession) -> None:
    account = await seed_account(session, "acme")
    first = await client.patch(
        "/api/v1/tenants/current",
        headers=account.headers,
        json={"contact_email": "sales@acme.example", "website": "https://acme.example"},
    )
    assert first.status_code == 200

    response = await client.patch(
        "/api/v1/tenants/current",
        headers=account.headers,
        json={"contact_email": None, "website": None, "export_markets": []},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["contact_email"] is None
    assert data["website"] is None
    assert data["export_markets"] == []
    assert data["name"] == "acme tenant"


async def test_update_requires_tenant_update_permission(
    client: AsyncClient, session: AsyncSession
) -> None:
    owner = await seed_account(session, "acme")
    for role in ("SALES_REP", "VIEWER", "SALES_MANAGER"):
        account = await seed_account(session, f"acme-{role.lower()}", role_code=role)
        response = await client.patch(
            "/api/v1/tenants/current",
            headers=account.headers,
            json={"name": "Hijacked"},
        )
        assert response.status_code == 403, response.text

    read = await client.get("/api/v1/tenants/current", headers=owner.headers)
    assert read.status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "   "},
        {"name": None},
        {"default_currency": "US"},
        {"default_currency": "usdollar"},
        {"default_currency": None},
        {"default_language": "EN_US"},
        {"default_language": "e"},
        {"default_language": None},
        {"contact_email": "not-an-email"},
        {"export_markets": ["x" * 81]},
        {"export_markets": [f"market-{index}" for index in range(31)]},
    ],
)
async def test_update_rejects_invalid_payload(
    client: AsyncClient, session: AsyncSession, payload: dict[str, Any]
) -> None:
    account = await seed_account(session, "acme")

    response = await client.patch("/api/v1/tenants/current", headers=account.headers, json=payload)

    assert response.status_code == 422, response.text


async def test_update_keeps_other_tenants_untouched(
    client: AsyncClient, session: AsyncSession
) -> None:
    first = await seed_account(session, "first")
    second = await seed_account(session, "second")

    response = await client.patch(
        "/api/v1/tenants/current",
        headers=first.headers,
        json={"name": "First Fasteners", "default_currency": "EUR"},
    )
    assert response.status_code == 200, response.text

    other = await client.get("/api/v1/tenants/current", headers=second.headers)
    assert other.status_code == 200
    other_data = other.json()["data"]
    assert other_data["id"] == str(second.tenant.id)
    assert other_data["name"] == "second tenant"
    assert other_data["default_currency"] == "USD"


async def test_update_records_audit_event(client: AsyncClient, session: AsyncSession) -> None:
    account = await seed_account(session, "acme")

    response = await client.patch(
        "/api/v1/tenants/current",
        headers=account.headers,
        json={"name": "Acme Fasteners", "default_currency": "eur"},
    )
    assert response.status_code == 200, response.text

    logs = (
        (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.tenant_id == account.tenant.id,
                    AuditLog.action == "tenant.profile.updated",
                    AuditLog.resource_type == "TENANT",
                    AuditLog.resource_id == account.tenant.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(logs) == 1
    assert set(logs[0].metadata_json["fields"]) == {"name", "default_currency"}
