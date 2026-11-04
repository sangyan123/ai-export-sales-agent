import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.audit import AuditService
from app.auth.service import IssuedTokens, login
from app.core.config import settings
from app.core.security import hash_password, hash_refresh_token
from app.db.session import commit_or_rollback
from app.db.tenant import set_tenant_context
from app.models.invitation import MemberInvitation
from app.models.tenant import Tenant, TenantMembership, User


@dataclass(frozen=True)
class AcceptedInvitation:
    tenant: Tenant
    user: User
    tokens: IssuedTokens


def generate_invitation_token() -> tuple[str, str]:
    raw_token = secrets.token_urlsafe(48)
    return raw_token, hash_refresh_token(raw_token)


async def _revoke_pending(session: AsyncSession, membership_id: uuid.UUID, now: datetime) -> None:
    pending = (
        await session.execute(
            select(MemberInvitation).where(
                MemberInvitation.membership_id == membership_id,
                MemberInvitation.accepted_at.is_(None),
                MemberInvitation.revoked_at.is_(None),
            )
        )
    ).scalars()
    for invitation in pending:
        invitation.revoked_at = now


async def issue_invitation(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
    user_id: uuid.UUID,
    created_by_id: uuid.UUID,
) -> tuple[str, MemberInvitation]:
    now = datetime.now(UTC)
    await _revoke_pending(session, membership_id, now)
    raw_token, token_hash = generate_invitation_token()
    invitation = MemberInvitation(
        user_id=user_id,
        tenant_id=tenant_id,
        membership_id=membership_id,
        token_hash=token_hash,
        expires_at=now + timedelta(seconds=settings.member_invitation_ttl_seconds),
        created_by_id=created_by_id,
    )
    session.add(invitation)
    return raw_token, invitation


async def accept_invitation(
    session: AsyncSession,
    *,
    token: str,
    display_name: str,
    password: str,
    request_id: str | None = None,
    ip_hash: str | None = None,
) -> AcceptedInvitation:
    invitation = await session.scalar(
        select(MemberInvitation)
        .where(MemberInvitation.token_hash == hash_refresh_token(token))
        .with_for_update()
    )
    now = datetime.now(UTC)
    if invitation is None:
        raise ApiError(404, "INVITATION_NOT_FOUND", "invitation link is invalid")
    if invitation.accepted_at is not None:
        raise ApiError(409, "INVITATION_ALREADY_ACCEPTED", "invitation has already been accepted")
    if invitation.revoked_at is not None:
        raise ApiError(409, "INVITATION_REVOKED", "invitation has been revoked")
    if invitation.expires_at <= now:
        raise ApiError(409, "INVITATION_EXPIRED", "invitation has expired")

    await set_tenant_context(session, invitation.tenant_id)
    tenant = await session.get(Tenant, invitation.tenant_id)
    if tenant is None or tenant.status != "ACTIVE":
        raise ApiError(403, "TENANT_DISABLED", "tenant is not active")

    membership = await session.get(TenantMembership, invitation.membership_id)
    if (
        membership is None
        or membership.tenant_id != invitation.tenant_id
        or membership.status != "INVITED"
    ):
        raise ApiError(409, "INVITATION_NOT_ACTIVE", "invitation is no longer active")

    user = await session.get(User, invitation.user_id)
    if user is None:
        raise ApiError(404, "INVITATION_NOT_FOUND", "invited account no longer exists")

    user.display_name = display_name
    user.password_hash = hash_password(password)
    user.status = "ACTIVE"
    membership.status = "ACTIVE"
    membership.joined_at = now
    invitation.accepted_at = now

    AuditService(session).record(
        tenant_id=tenant.id,
        actor_id=user.id,
        action="member.invite.accept",
        resource_type="TENANT_MEMBERSHIP",
        resource_id=membership.id,
        request_id=request_id,
        ip_hash=ip_hash,
        metadata={
            "user_id": str(user.id),
            "email": user.email,
            "role_code": membership.role_code,
        },
    )
    await session.flush()
    await commit_or_rollback(session)

    tokens = await login(
        session,
        email=user.email,
        password=password,
        tenant_id=tenant.id,
    )
    return AcceptedInvitation(tenant=tenant, user=user, tokens=tokens)
