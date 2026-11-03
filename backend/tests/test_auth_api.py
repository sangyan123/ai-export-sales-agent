import os
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.db.session import get_session
from app.db.tenant import set_tenant_context
from app.main import app
from app.models.tenant import Tenant, TenantMembership, User

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
PASSWORD = "correct-horse-battery"
PASSWORD_HASH = hash_password(PASSWORD)

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
class Seed:
    tenant: Tenant
    user: User
    membership: TenantMembership | None
    email: str


async def seed_user(
    session: AsyncSession,
    slug: str,
    *,
    role_code: str | None = "SALES_REP",
    user_status: str = "ACTIVE",
    tenant_status: str = "ACTIVE",
) -> Seed:
    tenant = Tenant(name=slug, slug=slug, status=tenant_status)
    session.add(tenant)
    await session.flush()
    await set_tenant_context(session, tenant.id)

    email = f"user@{slug}.example"
    user = User(
        email=email,
        password_hash=PASSWORD_HASH,
        display_name="Test User",
        status=user_status,
    )
    session.add(user)
    await session.flush()

    membership = None
    if role_code is not None:
        membership = TenantMembership(tenant_id=tenant.id, user_id=user.id, role_code=role_code)
        session.add(membership)
        await session.flush()
    return Seed(tenant=tenant, user=user, membership=membership, email=email)


def auth_header(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def login(
    client: AsyncClient,
    seed: Seed,
    *,
    password: str = PASSWORD,
    by_id: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"email": seed.email, "password": password}
    if by_id:
        payload["tenant_id"] = str(seed.tenant.id)
    else:
        payload["tenant_slug"] = seed.tenant.slug
    response = await client.post("/api/v1/auth/login", json=payload)
    return response


async def test_login_returns_tokens_and_current_user(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_user(session, "auth-login")

    response = await login(client, seed)

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["token_type"] == "Bearer"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in"] == 900

    me = await client.get("/api/v1/users/me", headers=auth_header(body["access_token"]))
    assert me.status_code == 200
    data = me.json()["data"]
    assert data["email"] == seed.email
    assert data["role"] == "SALES_REP"
    assert data["tenant"]["slug"] == seed.tenant.slug
    assert "quote:create" in data["permissions"]
    assert "pricing:update" not in data["permissions"]

    tenant = await client.get("/api/v1/tenants/current", headers=auth_header(body["access_token"]))
    assert tenant.status_code == 200
    assert tenant.json()["data"]["id"] == str(seed.tenant.id)


async def test_login_accepts_tenant_id(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_user(session, "auth-tenant-id")

    response = await login(client, seed, by_id=True)

    assert response.status_code == 200
    assert response.json()["data"]["access_token"]


@pytest.mark.parametrize("password", ["wrong-password", ""])
async def test_login_rejects_bad_password(
    client: AsyncClient, session: AsyncSession, password: str
) -> None:
    seed = await seed_user(session, "auth-bad-password")

    response = await login(client, seed, password=password)

    expected = 401 if password else 422
    assert response.status_code == expected


async def test_login_rejects_unknown_email(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": PASSWORD, "tenant_slug": "missing"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_login_rejects_non_member(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_user(session, "auth-no-member", role_code=None)

    response = await login(client, seed)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "TENANT_ACCESS_DENIED"


async def test_login_rejects_disabled_user(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_user(session, "auth-disabled-user", user_status="DISABLED")

    response = await login(client, seed)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "USER_DISABLED"


async def test_login_rejects_disabled_tenant(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_user(session, "auth-disabled-tenant", tenant_status="SUSPENDED")

    response = await login(client, seed)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "TENANT_DISABLED"


async def test_expired_and_malformed_tokens_are_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_user(session, "auth-token-errors")
    expired = create_access_token(
        user_id=seed.user.id,
        tenant_id=seed.tenant.id,
        membership_id=seed.membership.id,
        ttl_seconds=-60,
    )

    expired_response = await client.get("/api/v1/users/me", headers=auth_header(expired))
    assert expired_response.status_code == 401
    assert expired_response.json()["error"]["code"] == "TOKEN_EXPIRED"

    malformed_response = await client.get(
        "/api/v1/users/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert malformed_response.status_code == 401
    assert malformed_response.json()["error"]["code"] == "AUTH_INVALID"


async def test_refresh_rotates_tokens_and_detects_reuse(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_user(session, "auth-refresh")
    initial = (await login(client, seed)).json()["data"]

    rotated = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": initial["refresh_token"]}
    )
    assert rotated.status_code == 200
    rotated_data = rotated.json()["data"]
    assert rotated_data["refresh_token"] != initial["refresh_token"]

    replay = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": initial["refresh_token"]}
    )
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "REFRESH_TOKEN_REUSED"

    revoked_replacement = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": rotated_data["refresh_token"]}
    )
    assert revoked_replacement.status_code == 401

    still_valid_access = await client.get(
        "/api/v1/users/me", headers=auth_header(rotated_data["access_token"])
    )
    assert still_valid_access.status_code == 200


async def test_logout_revokes_refresh_token(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_user(session, "auth-logout")
    tokens = (await login(client, seed)).json()["data"]

    logout = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers=auth_header(tokens["access_token"]),
    )
    assert logout.status_code == 200
    assert logout.json()["data"] == {"revoked": True}

    reused = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "REFRESH_TOKEN_INVALID"


async def test_viewer_can_read_but_cannot_write(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_user(session, "auth-viewer", role_code="VIEWER")
    tokens = (await login(client, seed)).json()["data"]
    headers = auth_header(tokens["access_token"])

    listed = await client.get("/api/v1/products", headers=headers)
    assert listed.status_code == 200

    created = await client.post(
        "/api/v1/products",
        json={
            "product_code": "BOLT-M6-20",
            "product_name": "Hex bolt M6x20",
            "category": "BOLT",
            "sales_unit": "PCS",
        },
        headers=headers,
    )
    assert created.status_code == 403
    assert created.json()["error"]["code"] == "PERMISSION_DENIED"
    assert created.json()["error"]["details"][0]["permission"] == "product:create"


async def test_approver_cannot_create_quotes(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_user(session, "auth-approver", role_code="APPROVER")
    tokens = (await login(client, seed)).json()["data"]

    response = await client.post(
        "/api/v1/quotes",
        json={
            "currency": "USD",
            "items": [
                {
                    "product_id": str(uuid.uuid4()),
                    "quantity": "1",
                    "unit": "PCS",
                }
            ],
        },
        headers=auth_header(tokens["access_token"]),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    assert response.json()["error"]["details"][0]["permission"] == "quote:create"


async def test_sales_rep_cannot_change_prices(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_user(session, "auth-rep-pricing", role_code="SALES_REP")
    tokens = (await login(client, seed)).json()["data"]

    response = await client.post(
        "/api/v1/price-lists",
        json={"name": "2026 USD", "currency": "USD", "valid_from": "2026-01-01"},
        headers=auth_header(tokens["access_token"]),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    assert response.json()["error"]["details"][0]["permission"] == "pricing:update"


async def test_role_change_takes_effect_without_new_token(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_user(session, "auth-role-change", role_code="SALES_REP")
    tokens = (await login(client, seed)).json()["data"]
    headers = auth_header(tokens["access_token"])

    allowed = await client.post(
        "/api/v1/customers",
        json={"company_name": "Acme GmbH", "country_code": "DE"},
        headers=headers,
    )
    assert allowed.status_code == 201

    seed.membership.role_code = "VIEWER"
    await session.flush()

    denied = await client.post(
        "/api/v1/customers",
        json={"company_name": "Beta GmbH", "country_code": "DE"},
        headers=headers,
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "PERMISSION_DENIED"
