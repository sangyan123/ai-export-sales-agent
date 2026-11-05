import os
import uuid
from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.db.session import get_session
from app.main import app
from app.models.ai_provider import TenantAIProviderConfig
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
class ProviderSeed:
    rep_headers: dict[str, str]
    viewer_headers: dict[str, str]
    other_headers: dict[str, str]


def _bearer(tenant: Tenant, user: User, membership_id: uuid.UUID) -> dict[str, str]:
    token = create_access_token(
        user_id=user.id,
        tenant_id=tenant.id,
        membership_id=membership_id,
    )
    return {"Authorization": f"Bearer {token}"}


async def seed_provider(session: AsyncSession, slug: str) -> ProviderSeed:
    tenant = Tenant(name=slug, slug=slug)
    other_tenant = Tenant(name=f"{slug}-other", slug=f"{slug}-other")
    session.add_all([tenant, other_tenant])
    await session.flush()

    rep = User(email=f"rep@{slug}.example", password_hash=PASSWORD_HASH, display_name="Rep")
    viewer = User(
        email=f"viewer@{slug}.example", password_hash=PASSWORD_HASH, display_name="Viewer"
    )
    other_user = User(
        email=f"other@{slug}.example", password_hash=PASSWORD_HASH, display_name="Other"
    )
    session.add_all([rep, viewer, other_user])
    await session.flush()

    rep_membership = TenantMembership(tenant_id=tenant.id, user_id=rep.id, role_code="OWNER")
    viewer_membership = TenantMembership(tenant_id=tenant.id, user_id=viewer.id, role_code="VIEWER")
    other_membership = TenantMembership(
        tenant_id=other_tenant.id, user_id=other_user.id, role_code="OWNER"
    )
    session.add_all([rep_membership, viewer_membership, other_membership])
    await session.flush()

    return ProviderSeed(
        rep_headers=_bearer(tenant, rep, rep_membership.id),
        viewer_headers=_bearer(tenant, viewer, viewer_membership.id),
        other_headers=_bearer(other_tenant, other_user, other_membership.id),
    )


async def test_get_empty_returns_env_fallback(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_provider(session, "provider-empty")

    response = await client.get("/api/v1/settings/ai-provider", headers=seed.rep_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["api_key_set"] is False
    assert data["enabled"] is False
    assert "env_fallback" in data


async def test_update_and_masked_key(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_provider(session, "provider-update")

    response = await client.put(
        "/api/v1/settings/ai-provider",
        json={
            "provider": "openai-compatible",
            "api_key": "sk-proj-abcdef1234567890",
            "base_url": "https://api.deepseek.com/v1/",
            "model_id": "deepseek-chat",
            "enabled": True,
        },
        headers=seed.rep_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["provider"] == "openai-compatible"
    assert data["base_url"] == "https://api.deepseek.com/v1"
    assert data["model_id"] == "deepseek-chat"
    assert data["enabled"] is True
    assert data["api_key_set"] is True
    assert data["api_key_hint"] == "sk-p...7890"
    assert "abcdef1234567890" not in response.text


async def test_update_without_key_keeps_existing(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_provider(session, "provider-keep-key")

    await client.put(
        "/api/v1/settings/ai-provider",
        json={"provider": "openai", "api_key": "sk-first-key-12345678", "enabled": False},
        headers=seed.rep_headers,
    )
    second = await client.put(
        "/api/v1/settings/ai-provider",
        json={"provider": "openai", "model_id": "gpt-4o-mini", "enabled": False},
        headers=seed.rep_headers,
    )
    assert second.status_code == 200
    assert second.json()["data"]["api_key_set"] is True


async def test_enable_requires_api_key(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_provider(session, "provider-enable-nokey")

    response = await client.put(
        "/api/v1/settings/ai-provider",
        json={"provider": "openai", "enabled": True},
        headers=seed.rep_headers,
    )
    assert response.status_code == 422


async def test_viewer_cannot_update(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_provider(session, "provider-viewer-deny")

    response = await client.put(
        "/api/v1/settings/ai-provider",
        json={"provider": "openai", "enabled": False},
        headers=seed.viewer_headers,
    )
    assert response.status_code == 403


async def test_tenant_isolation(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_provider(session, "provider-isolation")

    await client.put(
        "/api/v1/settings/ai-provider",
        json={"provider": "openai", "api_key": "sk-tenant-one-12345678", "enabled": True},
        headers=seed.rep_headers,
    )

    response = await client.get("/api/v1/settings/ai-provider", headers=seed.other_headers)
    assert response.status_code == 200
    assert response.json()["data"]["api_key_set"] is False


async def test_test_endpoint_requires_config(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_provider(session, "provider-test-empty")

    response = await client.post("/api/v1/settings/ai-provider/test", headers=seed.rep_headers)
    assert response.status_code == 404


async def test_invalid_provider_rejected(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_provider(session, "provider-invalid")

    response = await client.put(
        "/api/v1/settings/ai-provider",
        json={"provider": "bogus-provider", "enabled": False},
        headers=seed.rep_headers,
    )
    assert response.status_code == 422
