import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.core.config import settings
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
    verify_dummy_password,
    verify_password,
)
from app.db.session import commit_or_rollback
from app.db.tenant import set_tenant_context
from app.models.auth import AuthRefreshToken
from app.models.tenant import Tenant, TenantMembership, User


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int
    refresh_expires_in: int


def _issue_tokens(
    session: AsyncSession,
    *,
    user: User,
    tenant: Tenant,
    membership: TenantMembership,
) -> tuple[IssuedTokens, AuthRefreshToken]:
    now = datetime.now(UTC)
    raw_token, token_hash = generate_refresh_token()
    record = AuthRefreshToken(
        user_id=user.id,
        tenant_id=tenant.id,
        membership_id=membership.id,
        token_hash=token_hash,
        expires_at=now + timedelta(seconds=settings.refresh_token_ttl_seconds),
    )
    session.add(record)
    tokens = IssuedTokens(
        access_token=create_access_token(
            user_id=user.id,
            tenant_id=tenant.id,
            membership_id=membership.id,
        ),
        refresh_token=raw_token,
        expires_in=settings.access_token_ttl_seconds,
        refresh_expires_in=settings.refresh_token_ttl_seconds,
    )
    return tokens, record


async def _resolve_tenant(
    session: AsyncSession,
    tenant_id: uuid.UUID | None,
    tenant_slug: str | None,
) -> Tenant:
    if tenant_id is not None:
        statement = select(Tenant).where(Tenant.id == tenant_id)
    elif tenant_slug is not None:
        statement = select(Tenant).where(Tenant.slug == tenant_slug.strip().lower())
    else:
        raise ApiError(400, "TENANT_REQUIRED", "tenant_id or tenant_slug is required")

    tenant = await session.scalar(statement)
    if tenant is None:
        raise ApiError(403, "TENANT_ACCESS_DENIED", "tenant not found or access denied")
    if tenant.status != "ACTIVE":
        raise ApiError(403, "TENANT_DISABLED", "tenant is not active")
    return tenant


async def _active_membership(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    membership_id: uuid.UUID | None = None,
) -> TenantMembership | None:
    conditions = [
        TenantMembership.tenant_id == tenant_id,
        TenantMembership.user_id == user_id,
        TenantMembership.status == "ACTIVE",
    ]
    if membership_id is not None:
        conditions.append(TenantMembership.id == membership_id)
    return await session.scalar(select(TenantMembership).where(*conditions))


async def login(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    tenant_id: uuid.UUID | None = None,
    tenant_slug: str | None = None,
) -> IssuedTokens:
    user = await session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        verify_dummy_password(password)
        raise ApiError(401, "INVALID_CREDENTIALS", "invalid email or password")
    if not verify_password(user.password_hash, password):
        raise ApiError(401, "INVALID_CREDENTIALS", "invalid email or password")
    if user.status != "ACTIVE":
        raise ApiError(403, "USER_DISABLED", "user is not active")

    tenant = await _resolve_tenant(session, tenant_id, tenant_slug)
    await set_tenant_context(session, tenant.id)
    membership = await _active_membership(session, tenant_id=tenant.id, user_id=user.id)
    if membership is None:
        raise ApiError(403, "TENANT_ACCESS_DENIED", "user is not an active tenant member")

    tokens, _ = _issue_tokens(session, user=user, tenant=tenant, membership=membership)
    user.last_login_at = datetime.now(UTC)
    await session.flush()
    await commit_or_rollback(session)
    return tokens


async def _revoke_all(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> None:
    await session.execute(
        update(AuthRefreshToken)
        .where(
            AuthRefreshToken.user_id == user_id,
            AuthRefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )


async def refresh(session: AsyncSession, raw_token: str) -> IssuedTokens:
    token_hash = hash_refresh_token(raw_token)
    record = await session.scalar(
        select(AuthRefreshToken).where(AuthRefreshToken.token_hash == token_hash)
    )
    now = datetime.now(UTC)
    if record is None:
        raise ApiError(401, "REFRESH_TOKEN_INVALID", "refresh token is invalid")
    if record.revoked_at is not None:
        if record.replaced_by_id is None:
            raise ApiError(401, "REFRESH_TOKEN_INVALID", "refresh token is no longer valid")
        await _revoke_all(session, record.user_id, now)
        await commit_or_rollback(session)
        raise ApiError(401, "REFRESH_TOKEN_REUSED", "refresh token has already been used")
    if record.expires_at <= now:
        record.revoked_at = now
        await commit_or_rollback(session)
        raise ApiError(401, "REFRESH_TOKEN_EXPIRED", "refresh token has expired")

    await set_tenant_context(session, record.tenant_id)
    user = await session.get(User, record.user_id)
    if user is None or user.status != "ACTIVE":
        record.revoked_at = now
        await commit_or_rollback(session)
        raise ApiError(403, "USER_DISABLED", "user is not active")
    tenant = await session.get(Tenant, record.tenant_id)
    if tenant is None or tenant.status != "ACTIVE":
        record.revoked_at = now
        await commit_or_rollback(session)
        raise ApiError(403, "TENANT_DISABLED", "tenant is not active")
    membership = await _active_membership(
        session,
        tenant_id=record.tenant_id,
        user_id=record.user_id,
        membership_id=record.membership_id,
    )
    if membership is None:
        record.revoked_at = now
        await commit_or_rollback(session)
        raise ApiError(403, "TENANT_ACCESS_DENIED", "user is not an active tenant member")

    tokens, replacement = _issue_tokens(session, user=user, tenant=tenant, membership=membership)
    await session.flush()
    record.revoked_at = now
    record.replaced_by_id = replacement.id
    await session.flush()
    await commit_or_rollback(session)
    return tokens


async def logout(session: AsyncSession, *, user_id: uuid.UUID, raw_token: str) -> None:
    record = await session.scalar(
        select(AuthRefreshToken).where(
            AuthRefreshToken.token_hash == hash_refresh_token(raw_token),
            AuthRefreshToken.user_id == user_id,
        )
    )
    if record is None or record.revoked_at is not None:
        return
    record.revoked_at = datetime.now(UTC)
    await session.flush()
    await commit_or_rollback(session)
