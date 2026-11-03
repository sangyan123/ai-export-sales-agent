import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError, get_request_id
from app.core.permissions import Permission, permissions_for_role
from app.core.security import AccessTokenError, AccessTokenExpired, decode_access_token
from app.db.session import get_session
from app.db.tenant import set_tenant_context
from app.models.tenant import Tenant, TenantMembership, User

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@dataclass(frozen=True)
class RequestContext:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    membership_id: uuid.UUID
    role_code: str
    permissions: frozenset[Permission]
    request_id: str


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("Authorization")
    if not authorization:
        raise ApiError(401, "AUTH_REQUIRED", "Authorization header is required")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ApiError(401, "AUTH_INVALID", "Authorization header must be a Bearer token")
    return token.strip()


async def get_request_context(
    request: Request,
    session: SessionDep,
) -> RequestContext:
    try:
        claims = decode_access_token(_bearer_token(request))
    except AccessTokenExpired as exc:
        raise ApiError(401, "TOKEN_EXPIRED", "access token has expired") from exc
    except AccessTokenError as exc:
        raise ApiError(401, "AUTH_INVALID", "access token is invalid") from exc

    await set_tenant_context(session, claims.tenant_id)

    membership = await session.scalar(
        select(TenantMembership).where(
            TenantMembership.id == claims.membership_id,
            TenantMembership.tenant_id == claims.tenant_id,
            TenantMembership.user_id == claims.user_id,
            TenantMembership.status == "ACTIVE",
        )
    )
    if membership is None:
        raise ApiError(403, "TENANT_ACCESS_DENIED", "user is not an active tenant member")

    user = await session.get(User, claims.user_id)
    if user is None or user.status != "ACTIVE":
        raise ApiError(403, "USER_DISABLED", "user is not active")

    tenant = await session.get(Tenant, claims.tenant_id)
    if tenant is None or tenant.status != "ACTIVE":
        raise ApiError(403, "TENANT_DISABLED", "tenant is not active")

    return RequestContext(
        tenant_id=claims.tenant_id,
        user_id=claims.user_id,
        membership_id=membership.id,
        role_code=membership.role_code,
        permissions=permissions_for_role(membership.role_code),
        request_id=get_request_id(request),
    )


ContextDep = Annotated[RequestContext, Depends(get_request_context)]
PermissionChecker = Callable[[RequestContext], Awaitable[RequestContext]]


def require_permission(permission: Permission) -> PermissionChecker:
    async def check(context: ContextDep) -> RequestContext:
        if permission not in context.permissions:
            raise ApiError(
                403,
                "PERMISSION_DENIED",
                "role is not allowed to perform this action",
                [{"permission": permission.value, "role": context.role_code}],
            )
        return context

    return check
