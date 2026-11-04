import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password, hash_refresh_token
from app.db.session import get_session
from app.db.tenant import set_tenant_context
from app.main import app
from app.models.audit import AuditLog
from app.models.auth import AuthRefreshToken
from app.models.invitation import MemberInvitation
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


def _members_url(account: Account) -> str:
    return f"/api/v1/tenants/{account.tenant.id}/members"


async def invite_member(
    client: AsyncClient,
    account: Account,
    *,
    email: str = "invited@acme.example",
    display_name: str = "Invited Member",
    role_code: str = "SALES_REP",
) -> dict:
    response = await client.post(
        f"{_members_url(account)}/invitations",
        headers=account.headers,
        json={"email": email, "display_name": display_name, "role_code": role_code},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _member_headers(member: Member, tenant: Tenant) -> dict[str, str]:
    token = create_access_token(
        user_id=member.user.id,
        tenant_id=tenant.id,
        membership_id=member.membership.id,
    )
    return {"Authorization": f"Bearer {token}"}


async def test_invite_member_creates_pending_membership(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await seed_account(session, "acme")

    data = await invite_member(
        client,
        account,
        email=" New.Hire@Acme.Example ",
        display_name="  New Hire  ",
        role_code="SALES_REP",
    )

    membership = data["member"]
    assert membership["email"] == "new.hire@acme.example"
    assert membership["display_name"] == "New Hire"
    assert membership["role_code"] == "SALES_REP"
    assert membership["status"] == "INVITED"
    assert membership["user_status"] == "ACTIVE"

    raw_token = data["invitation"]["token"]
    assert len(raw_token) >= 40
    assert data["invitation"]["expires_at"]

    invitation = await session.scalar(
        select(MemberInvitation).where(
            MemberInvitation.membership_id == uuid.UUID(membership["id"])
        )
    )
    assert invitation is not None
    assert invitation.token_hash == hash_refresh_token(raw_token)
    assert invitation.token_hash != raw_token
    assert invitation.accepted_at is None
    assert invitation.revoked_at is None

    log = await session.scalar(
        select(AuditLog).where(
            AuditLog.tenant_id == account.tenant.id,
            AuditLog.action == "member.invite",
            AuditLog.resource_id == uuid.UUID(membership["id"]),
        )
    )
    assert log is not None
    assert log.actor_id == account.user.id
    assert log.metadata_json["email"] == "new.hire@acme.example"
    assert log.metadata_json["role_code"] == "SALES_REP"

    login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "new.hire@acme.example",
            "password": "something-random",
            "tenant_slug": "acme",
        },
    )
    assert login.status_code == 401, login.text


async def test_invite_rejects_existing_member_and_registered_email(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await seed_account(session, "acme")
    await add_member(session, account.tenant, "active@acme.example", "SALES_REP")
    await add_member(
        session, account.tenant, "disabled@acme.example", "SALES_REP", status="DISABLED"
    )
    other = await seed_account(session, "other")

    active = await client.post(
        f"{_members_url(account)}/invitations",
        headers=account.headers,
        json={
            "email": "active@acme.example",
            "display_name": "Active",
            "role_code": "VIEWER",
        },
    )
    assert active.status_code == 409, active.text
    assert active.json()["error"]["code"] == "MEMBER_ALREADY_EXISTS"

    disabled = await client.post(
        f"{_members_url(account)}/invitations",
        headers=account.headers,
        json={
            "email": "disabled@acme.example",
            "display_name": "Disabled",
            "role_code": "VIEWER",
        },
    )
    assert disabled.status_code == 409, disabled.text
    assert disabled.json()["error"]["code"] == "MEMBER_DISABLED"

    foreign = await client.post(
        f"{_members_url(account)}/invitations",
        headers=account.headers,
        json={
            "email": other.user.email,
            "display_name": "Other Owner",
            "role_code": "VIEWER",
        },
    )
    assert foreign.status_code == 409, foreign.text
    assert foreign.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"

    invalid = await client.post(
        f"{_members_url(account)}/invitations",
        headers=account.headers,
        json={"email": "not-an-email", "display_name": "Bad", "role_code": "VIEWER"},
    )
    assert invalid.status_code == 422, invalid.text


async def test_reinvite_pending_member_replaces_link(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await seed_account(session, "acme")
    first = await invite_member(client, account, role_code="SALES_REP")
    membership_id = uuid.UUID(first["member"]["id"])

    second = await invite_member(
        client,
        account,
        display_name="Renamed Member",
        role_code="SALES_MANAGER",
    )

    assert second["member"]["id"] == str(membership_id)
    assert second["member"]["display_name"] == "Renamed Member"
    assert second["member"]["role_code"] == "SALES_MANAGER"
    assert second["invitation"]["token"] != first["invitation"]["token"]

    invitations = (
        (
            await session.execute(
                select(MemberInvitation)
                .where(MemberInvitation.membership_id == membership_id)
                .order_by(MemberInvitation.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    assert len(invitations) == 2
    assert invitations[0].revoked_at is not None
    assert invitations[1].revoked_at is None

    accept_old = await client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "token": first["invitation"]["token"],
            "display_name": "Renamed Member",
            "password": "Invitee123!",
        },
    )
    assert accept_old.status_code == 409, accept_old.text
    assert accept_old.json()["error"]["code"] == "INVITATION_REVOKED"


async def test_resend_and_cancel_invitation(client: AsyncClient, session: AsyncSession) -> None:
    account = await seed_account(session, "acme")
    invited = await invite_member(client, account)
    membership_id = uuid.UUID(invited["member"]["id"])

    resent = await client.post(
        f"{_members_url(account)}/{membership_id}/invitations",
        headers=account.headers,
    )
    assert resent.status_code == 200, resent.text
    resent_token = resent.json()["data"]["invitation"]["token"]
    assert resent_token != invited["invitation"]["token"]

    stale = await client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "token": invited["invitation"]["token"],
            "display_name": "Invited Member",
            "password": "Invitee123!",
        },
    )
    assert stale.status_code == 409, stale.text

    active_rep = await add_member(session, account.tenant, "rep@acme.example", "SALES_REP")
    not_pending = await client.post(
        f"{_members_url(account)}/{active_rep.membership.id}/invitations",
        headers=account.headers,
    )
    assert not_pending.status_code == 409, not_pending.text
    assert not_pending.json()["error"]["code"] == "INVITATION_NOT_PENDING"

    cancelled = await client.delete(
        f"{_members_url(account)}/{membership_id}/invitations",
        headers=account.headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"]["cancelled"] is True

    assert (
        await session.scalar(select(TenantMembership).where(TenantMembership.id == membership_id))
        is None
    )
    assert await session.scalar(select(User).where(User.email == "invited@acme.example")) is None

    actions = (
        (
            await session.execute(
                select(AuditLog.action).where(AuditLog.tenant_id == account.tenant.id)
            )
        )
        .scalars()
        .all()
    )
    assert "member.invite" in actions
    assert "member.invite.resend" in actions
    assert "member.invite.cancel" in actions

    accept_cancelled = await client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "token": resent_token,
            "display_name": "Invited Member",
            "password": "Invitee123!",
        },
    )
    assert accept_cancelled.status_code == 404, accept_cancelled.text
    assert accept_cancelled.json()["error"]["code"] == "INVITATION_NOT_FOUND"


async def test_accept_invitation_activates_account(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await seed_account(session, "acme")
    invited = await invite_member(client, account, display_name="Pending Name")
    raw_token = invited["invitation"]["token"]

    weak = await client.post(
        "/api/v1/auth/invitations/accept",
        json={"token": raw_token, "display_name": "New Member", "password": "short"},
    )
    assert weak.status_code == 422, weak.text

    response = await client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "token": raw_token,
            "display_name": "New Member",
            "password": "Invitee123!",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["tenant_slug"] == "acme"
    assert data["email"] == "invited@acme.example"
    assert data["tokens"]["access_token"]
    assert data["tokens"]["refresh_token"]

    user = await session.scalar(select(User).where(User.email == "invited@acme.example"))
    assert user is not None
    membership = await session.scalar(
        select(TenantMembership).where(TenantMembership.user_id == user.id)
    )
    assert membership is not None
    assert membership.status == "ACTIVE"
    assert user.display_name == "New Member"

    invitation = await session.scalar(
        select(MemberInvitation).where(MemberInvitation.membership_id == membership.id)
    )
    assert invitation is not None
    assert invitation.accepted_at is not None

    reused = await client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "token": raw_token,
            "display_name": "New Member",
            "password": "Invitee123!",
        },
    )
    assert reused.status_code == 409, reused.text
    assert reused.json()["error"]["code"] == "INVITATION_ALREADY_ACCEPTED"

    login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "invited@acme.example",
            "password": "Invitee123!",
            "tenant_slug": "acme",
        },
    )
    assert login.status_code == 200, login.text

    log = await session.scalar(
        select(AuditLog).where(
            AuditLog.tenant_id == account.tenant.id,
            AuditLog.action == "member.invite.accept",
        )
    )
    assert log is not None
    assert log.actor_id == user.id


async def test_accept_invitation_rejects_invalid_and_expired_links(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await seed_account(session, "acme")
    invited = await invite_member(client, account)

    unknown = await client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "token": "unknown-token-value-123456",
            "display_name": "Nobody",
            "password": "Invitee123!",
        },
    )
    assert unknown.status_code == 404, unknown.text
    assert unknown.json()["error"]["code"] == "INVITATION_NOT_FOUND"

    invitation = await session.scalar(
        select(MemberInvitation).where(
            MemberInvitation.membership_id == uuid.UUID(invited["member"]["id"])
        )
    )
    assert invitation is not None
    invitation.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await session.flush()

    expired = await client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "token": invited["invitation"]["token"],
            "display_name": "Late Member",
            "password": "Invitee123!",
        },
    )
    assert expired.status_code == 409, expired.text
    assert expired.json()["error"]["code"] == "INVITATION_EXPIRED"


async def test_invitation_endpoints_require_permission(
    client: AsyncClient, session: AsyncSession
) -> None:
    manager = await seed_account(session, "manager", role_code="SALES_MANAGER")
    invited = await add_member(
        session, manager.tenant, "pending@manager.example", "VIEWER", status="INVITED"
    )

    create = await client.post(
        f"{_members_url(manager)}/invitations",
        headers=manager.headers,
        json={
            "email": "new@manager.example",
            "display_name": "New",
            "role_code": "VIEWER",
        },
    )
    assert create.status_code == 403, create.text

    resend = await client.post(
        f"{_members_url(manager)}/{invited.membership.id}/invitations",
        headers=manager.headers,
    )
    assert resend.status_code == 403, resend.text

    cancel = await client.delete(
        f"{_members_url(manager)}/{invited.membership.id}/invitations",
        headers=manager.headers,
    )
    assert cancel.status_code == 403, cancel.text


async def test_disable_member_revokes_sessions_and_audits(
    client: AsyncClient, session: AsyncSession
) -> None:
    account = await seed_account(session, "acme")
    rep = await add_member(session, account.tenant, "rep@acme.example", "SALES_REP")
    rep_headers = _member_headers(rep, account.tenant)

    token = AuthRefreshToken(
        user_id=rep.user.id,
        tenant_id=account.tenant.id,
        membership_id=rep.membership.id,
        token_hash="a" * 64,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    session.add(token)
    await session.flush()

    response = await client.patch(
        f"{_members_url(account)}/{rep.membership.id}/status",
        headers=account.headers,
        json={"status": "DISABLED"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "DISABLED"

    await session.refresh(token)
    assert token.revoked_at is not None

    denied = await client.get(_members_url(account), headers=rep_headers)
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "TENANT_ACCESS_DENIED"

    log = await session.scalar(
        select(AuditLog).where(
            AuditLog.tenant_id == account.tenant.id,
            AuditLog.action == "member.disable",
            AuditLog.resource_id == rep.membership.id,
        )
    )
    assert log is not None
    assert log.metadata_json["previous_status"] == "ACTIVE"
    assert log.metadata_json["status"] == "DISABLED"


async def test_enable_member_writes_audit(client: AsyncClient, session: AsyncSession) -> None:
    account = await seed_account(session, "acme")
    rep = await add_member(
        session, account.tenant, "rep@acme.example", "SALES_REP", status="DISABLED"
    )

    response = await client.patch(
        f"{_members_url(account)}/{rep.membership.id}/status",
        headers=account.headers,
        json={"status": "ACTIVE"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "ACTIVE"

    await session.refresh(rep.membership)
    assert rep.membership.status == "ACTIVE"

    log = await session.scalar(
        select(AuditLog).where(
            AuditLog.tenant_id == account.tenant.id,
            AuditLog.action == "member.enable",
            AuditLog.resource_id == rep.membership.id,
        )
    )
    assert log is not None


async def test_update_member_status_guards(client: AsyncClient, session: AsyncSession) -> None:
    account = await seed_account(session, "acme")
    invited = await add_member(
        session, account.tenant, "invited@acme.example", "VIEWER", status="INVITED"
    )

    not_accepted = await client.patch(
        f"{_members_url(account)}/{invited.membership.id}/status",
        headers=account.headers,
        json={"status": "DISABLED"},
    )
    assert not_accepted.status_code == 409, not_accepted.text
    assert not_accepted.json()["error"]["code"] == "INVITATION_NOT_ACCEPTED"

    self_disable = await client.patch(
        f"{_members_url(account)}/{account.membership.id}/status",
        headers=account.headers,
        json={"status": "DISABLED"},
    )
    assert self_disable.status_code == 409, self_disable.text
    assert self_disable.json()["error"]["code"] == "SELF_DISABLE_NOT_ALLOWED"

    invalid = await client.patch(
        f"{_members_url(account)}/{account.membership.id}/status",
        headers=account.headers,
        json={"status": "INVITED"},
    )
    assert invalid.status_code == 422, invalid.text

    admin = await seed_account(session, "admin", role_code="TENANT_ADMIN")
    owner = await add_member(session, admin.tenant, "second-owner@admin.example", "OWNER")
    last_owner = await client.patch(
        f"{_members_url(admin)}/{owner.membership.id}/status",
        headers=admin.headers,
        json={"status": "DISABLED"},
    )
    assert last_owner.status_code == 409, last_owner.text
    assert last_owner.json()["error"]["code"] == "LAST_OWNER_PROTECTED"


async def test_update_member_status_requires_permission(
    client: AsyncClient, session: AsyncSession
) -> None:
    manager = await seed_account(session, "manager", role_code="SALES_MANAGER")
    rep = await add_member(session, manager.tenant, "rep@manager.example", "SALES_REP")

    response = await client.patch(
        f"{_members_url(manager)}/{rep.membership.id}/status",
        headers=manager.headers,
        json={"status": "DISABLED"},
    )
    assert response.status_code == 403, response.text
