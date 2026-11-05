import os
import uuid
from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.db.session import get_session
from app.main import app
from app.models.ai_usage import AIUsageRecord
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
class UsageSeed:
    tenant: Tenant
    other_tenant: Tenant
    rep_headers: dict[str, str]
    other_headers: dict[str, str]


def _bearer(tenant: Tenant, user: User, membership_id: uuid.UUID) -> dict[str, str]:
    token = create_access_token(
        user_id=user.id,
        tenant_id=tenant.id,
        membership_id=membership_id,
    )
    return {"Authorization": f"Bearer {token}"}


async def seed_usage(session: AsyncSession, slug: str) -> UsageSeed:
    tenant = Tenant(name=slug, slug=slug)
    other_tenant = Tenant(name=f"{slug}-other", slug=f"{slug}-other")
    session.add_all([tenant, other_tenant])
    await session.flush()

    rep = User(email=f"rep@{slug}.example", password_hash=PASSWORD_HASH, display_name="Rep")
    other_user = User(
        email=f"other@{slug}.example", password_hash=PASSWORD_HASH, display_name="Other"
    )
    session.add_all([rep, other_user])
    await session.flush()

    rep_membership = TenantMembership(tenant_id=tenant.id, user_id=rep.id, role_code="SALES_MANAGER")
    other_membership = TenantMembership(
        tenant_id=other_tenant.id, user_id=other_user.id, role_code="SALES_MANAGER"
    )
    session.add_all([rep_membership, other_membership])
    await session.flush()

    records = [
        AIUsageRecord(
            tenant_id=tenant.id,
            operation_type="INQUIRY_PARSE",
            model_id="gpt-4o-mini",
            provider="openai",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            duration_ms=1200,
            status="SUCCESS",
        ),
        AIUsageRecord(
            tenant_id=tenant.id,
            operation_type="EMAIL_GENERATE",
            model_id="gpt-4o-mini",
            provider="openai",
            prompt_tokens=200,
            completion_tokens=100,
            total_tokens=300,
            duration_ms=900,
            status="SUCCESS",
        ),
    ]
    session.add_all(records)
    await session.flush()

    return UsageSeed(
        tenant=tenant,
        other_tenant=other_tenant,
        rep_headers=_bearer(tenant, rep, rep_membership.id),
        other_headers=_bearer(other_tenant, other_user, other_membership.id),
    )


async def test_usage_summary_totals(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_usage(session, "usage-summary")

    response = await client.get("/api/v1/usage/summary", headers=seed.rep_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["call_count"] == 2
    assert data["prompt_tokens"] == 300
    assert data["completion_tokens"] == 150
    assert data["total_tokens"] == 450
    assert data["total_duration_ms"] == 2100
    assert data["by_operation"]["INQUIRY_PARSE"]["call_count"] == 1
    assert data["by_operation"]["INQUIRY_PARSE"]["total_tokens"] == 150
    assert data["by_operation"]["EMAIL_GENERATE"]["total_tokens"] == 300


async def test_usage_records_list_and_filter(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_usage(session, "usage-records")

    response = await client.get("/api/v1/usage/records", headers=seed.rep_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 2
    assert len(body["data"]) == 2

    filtered = await client.get(
        "/api/v1/usage/records",
        params={"operation_type": "EMAIL_GENERATE"},
        headers=seed.rep_headers,
    )
    assert filtered.status_code == 200
    fbody = filtered.json()
    assert fbody["meta"]["total"] == 1
    assert fbody["data"][0]["operation_type"] == "EMAIL_GENERATE"
    assert fbody["data"][0]["total_tokens"] == 300


async def test_usage_records_rejects_unknown_operation(
    client: AsyncClient, session: AsyncSession
) -> None:
    seed = await seed_usage(session, "usage-invalid-op")

    response = await client.get(
        "/api/v1/usage/records",
        params={"operation_type": "BOGUS"},
        headers=seed.rep_headers,
    )
    assert response.status_code == 422


async def test_usage_tenant_isolation(client: AsyncClient, session: AsyncSession) -> None:
    seed = await seed_usage(session, "usage-isolation")

    summary = await client.get("/api/v1/usage/summary", headers=seed.other_headers)
    assert summary.status_code == 200
    assert summary.json()["data"]["call_count"] == 0

    records = await client.get("/api/v1/usage/records", headers=seed.other_headers)
    assert records.status_code == 200
    assert records.json()["meta"]["total"] == 0
