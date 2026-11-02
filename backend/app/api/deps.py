import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError, get_request_id
from app.db.session import get_session
from app.db.tenant import set_tenant_context
from app.models.tenant import Tenant, TenantMembership, User

TENANT_HEADER = "X-Tenant-Id"
USER_HEADER = "X-User-Id"

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@dataclass(frozen=True)
class RequestContext:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    request_id: str


def _parse_uuid_header(request: Request, header: str) -> uuid.UUID:
    raw = request.headers.get(header)
    if not raw:
        raise ApiError(401, "AUTH_REQUIRED", f"{header} header is required")
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise ApiError(401, "AUTH_INVALID", f"{header} must be a UUID") from exc


async def get_request_context(
    request: Request,
    session: SessionDep,
) -> RequestContext:
    """Temporary header-based identity until JWT auth lands.

    Membership and user status are re-checked on every request; the tenant
    header is never trusted on its own.
    """
    tenant_id = _parse_uuid_header(request, TENANT_HEADER)
    user_id = _parse_uuid_header(request, USER_HEADER)

    await set_tenant_context(session, tenant_id)

    membership_id = await session.scalar(
        select(TenantMembership.id).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user_id,
            TenantMembership.status == "ACTIVE",
        )
    )
    if membership_id is None:
        raise ApiError(403, "TENANT_ACCESS_DENIED", "user is not an active tenant member")

    user = await session.get(User, user_id)
    if user is None or user.status != "ACTIVE":
        raise ApiError(403, "USER_DISABLED", "user is not active")

    tenant = await session.get(Tenant, tenant_id)
    if tenant is None or tenant.status != "ACTIVE":
        raise ApiError(403, "TENANT_DISABLED", "tenant is not active")

    return RequestContext(
        tenant_id=tenant_id,
        user_id=user_id,
        request_id=get_request_id(request),
    )


ContextDep = Annotated[RequestContext, Depends(get_request_context)]
