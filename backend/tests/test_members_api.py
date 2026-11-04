import os
from dataclasses import dataclass

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
    membership: TenantMembership
    headers: dict[str, str]


@dataclass(frozen=True)
class Member:
    user: User
    membership: TenantMembership


async def seed_account(session: AsyncSession, slug: str, role_code: str = "OWNER") -> Account:
    tenant = Tenant(name=f"{slug} tenant", slug=slug)
    session.add(tenant)
    await session.flush()
    await set_tenant_context(session, tenant.id)

    user = User(email=f"owner@{slug}.example", password_hash=PASSWORD_HASH, display_name="Owner")
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
        membership=membership,
        headers={"Authorization": f"Bearer {token}"},
    )


async def add_member(
    session: AsyncSession,
    tenant: Tenant,
    email: str,
    role_code: str,
    status: str = "ACTIVE",
    display_name: str = "Member",
) -> Member:
    await set_tenant_context(session, tenant.id)
    user = User(email=email, password_hash=PASSWORD_HASH, display_name=display_name)
    session.add(user)
    await session.flush()
    membership = TenantMembership(
        tenant_id=tenant.id,
        user_id=user.id,
        role_code=role_code,
        status=status,
    )
    session.add(membership)
    await session.flush()
    return Member(user=user, membership=membership)


async def test_list_members_returns_tenant_members(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await seed_account(session, "acme")
    rep = await add_member(
        session, account.tenant, "rep@acme.example", "SALES_REP", display_name="Sales Rep"
    )

    response = await client.get(
        f"/api/v1/tenants/{account.tenant.id}/members", headers=account.headers
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["total"] == 2
    assert payload["meta"]["page"] == 1
    assert payload["meta"]["page_size"] == 20
    members = {item["email"]: item for item in payload["data"]}
    assert set(members) == {"owner@acme.example", "rep@acme.example"}
    owner_entry = members["owner@acme.example"]
    assert owner_entry["user_id"] == str(account.user.id)
    assert owner_entry["display_name"] == "Owner"
    assert owner_entry["role_code"] == "OWNER"
    assert owner_entry["status"] == "ACTIVE"
    assert owner_entry["user_status"] == "ACTIVE"
    assert owner_entry["joined_at"]
    rep_entry = members["rep@acme.example"]
    assert rep_entry["id"] == str(rep.membership.id)
    assert rep_entry["role_code"] == "SALES_REP"
    assert rep_entry["display_name"] == "Sales Rep"


async def test_list_members_filters(client: AsyncClient, session: AsyncSession) -> None:
    account = await seed_account(session, "acme")
    await add_member(session, account.tenant, "rep@acme.example", "SALES_REP")
    await add_member(
        session,
        account.tenant,
        "invited@acme.example",
        "VIEWER",
        status="INVITED",
        display_name="Invited Viewer",
    )

    url = f"/api/v1/tenants/{account.tenant.id}/members"
    by_query = await client.get(url, headers=account.headers, params={"q": "invited"})
    assert by_query.status_code == 200, by_query.text
    assert [item["email"] for item in by_query.json()["data"]] == ["invited@acme.example"]

    by_role = await client.get(url, headers=account.headers, params={"role_code": "SALES_REP"})
    assert by_role.status_code == 200, by_role.text
    assert [item["email"] for item in by_role.json()["data"]] == ["rep@acme.example"]

    by_status = await client.get(url, headers=account.headers, params={"status": "INVITED"})
    assert by_status.status_code == 200, by_status.text
    assert [item["email"] for item in by_status.json()["data"]] == ["invited@acme.example"]

    invalid_role = await client.get(url, headers=account.headers, params={"role_code": "ADMIN"})
    assert invalid_role.status_code == 422, invalid_role.text


async def test_list_members_requires_member_read(
    client: AsyncClient, session: AsyncSession
) -> None:
    for role in ("SALES_MANAGER", "SALES_REP", "VIEWER", "APPROVER"):
        account = await seed_account(session, f"acme-{role.lower()}", role_code=role)
        response = await client.get(
            f"/api/v1/tenants/{account.tenant.id}/members", headers=account.headers
        )
        assert response.status_code == 403, (role, response.text)


async def test_list_members_rejects_other_tenant(
    client: AsyncClient, session: AsyncSession
) -> None:
    first = await seed_account(session, "first")
    second = await seed_account(session, "second")

    response = await client.get(
        f"/api/v1/tenants/{second.tenant.id}/members", headers=first.headers
    )

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "TENANT_ACCESS_DENIED"


async def test_update_member_role(client: AsyncClient, session: AsyncSession) -> None:
    account = await seed_account(session, "acme")
    rep = await add_member(session, account.tenant, "rep@acme.example", "SALES_REP")

    response = await client.patch(
        f"/api/v1/tenants/{account.tenant.id}/members/{rep.membership.id}",
        headers=account.headers,
        json={"role_code": "SALES_MANAGER"},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["id"] == str(rep.membership.id)
    assert data["role_code"] == "SALES_MANAGER"
    assert data["email"] == "rep@acme.example"

    await session.refresh(rep.membership)
    assert rep.membership.role_code == "SALES_MANAGER"

    log = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.tenant_id == account.tenant.id,
                AuditLog.action == "member.role.update",
                AuditLog.resource_type == "TENANT_MEMBERSHIP",
                AuditLog.resource_id == rep.membership.id,
            )
        )
    ).scalar_one()
    assert log.actor_id == account.user.id
    assert log.metadata_json == {
        "user_id": str(rep.user.id),
        "previous_role": "SALES_REP",
        "role_code": "SALES_MANAGER",
    }


async def test_update_member_role_is_idempotent(client: AsyncClient, session: AsyncSession) -> None:
    account = await seed_account(session, "acme")
    rep = await add_member(session, account.tenant, "rep@acme.example", "SALES_REP")

    response = await client.patch(
        f"/api/v1/tenants/{account.tenant.id}/members/{rep.membership.id}",
        headers=account.headers,
        json={"role_code": "SALES_REP"},
    )

    assert response.status_code == 200, response.text
    logs = (
        (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.tenant_id == account.tenant.id,
                    AuditLog.action == "member.role.update",
                )
            )
        )
        .scalars()
        .all()
    )
    assert logs == []


async def test_update_role_protects_last_active_owner(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await seed_account(session, "acme")
    await add_member(
        session, account.tenant, "disabled-owner@acme.example", "OWNER", status="DISABLED"
    )

    response = await client.patch(
        f"/api/v1/tenants/{account.tenant.id}/members/{account.membership.id}",
        headers=account.headers,
        json={"role_code": "TENANT_ADMIN"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "LAST_OWNER_PROTECTED"

    second_owner = await add_member(session, account.tenant, "owner2@acme.example", "OWNER")
    allowed = await client.patch(
        f"/api/v1/tenants/{account.tenant.id}/members/{account.membership.id}",
        headers=account.headers,
        json={"role_code": "TENANT_ADMIN"},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["data"]["role_code"] == "TENANT_ADMIN"

    await session.refresh(second_owner.membership)
    assert second_owner.membership.role_code == "OWNER"


async def test_update_member_role_rejects_unknown_member(
    client: AsyncClient, session: AsyncSession
) -> None:
    first = await seed_account(session, "first")
    second = await seed_account(session, "second")

    response = await client.patch(
        f"/api/v1/tenants/{first.tenant.id}/members/{second.membership.id}",
        headers=first.headers,
        json={"role_code": "VIEWER"},
    )

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "MEMBER_NOT_FOUND"


async def test_update_member_role_requires_permission(
    client: AsyncClient, session: AsyncSession
) -> None:
    manager = await seed_account(session, "manager", role_code="SALES_MANAGER")
    viewer = await seed_account(session, "viewer", role_code="VIEWER")
    rep = await add_member(session, manager.tenant, "rep@manager.example", "SALES_REP")

    for account in (manager, viewer):
        response = await client.patch(
            f"/api/v1/tenants/{manager.tenant.id}/members/{rep.membership.id}",
            headers=account.headers,
            json={"role_code": "VIEWER"},
        )
        assert response.status_code == 403, response.text


async def test_update_member_role_validates_role(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await seed_account(session, "acme")
    rep = await add_member(session, account.tenant, "rep@acme.example", "SALES_REP")

    response = await client.patch(
        f"/api/v1/tenants/{account.tenant.id}/members/{rep.membership.id}",
        headers=account.headers,
        json={"role_code": "ADMIN"},
    )

    assert response.status_code == 422, response.text
