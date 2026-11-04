import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import envelope, iso_datetime
from app.api.deps import RequestContext, SessionDep, require_permission
from app.api.enums import MemberRole, MembershipStatus
from app.api.errors import ApiError
from app.audit import AuditService, client_ip_hash
from app.core.permissions import Permission
from app.db.session import commit_or_rollback
from app.db.tenant import set_tenant_context
from app.models.tenant import TenantMembership, User

router = APIRouter(prefix="/tenants/{tenant_id}/members", tags=["members"])

MemberReadContext = Annotated[RequestContext, Depends(require_permission(Permission.MEMBER_READ))]
MemberUpdateRoleContext = Annotated[
    RequestContext, Depends(require_permission(Permission.MEMBER_UPDATE_ROLE))
]


class MemberRoleUpdate(BaseModel):
    role_code: MemberRole


def _member_detail(membership: TenantMembership, user: User) -> dict[str, Any]:
    return {
        "id": str(membership.id),
        "user_id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "user_status": user.status,
        "role_code": membership.role_code,
        "status": membership.status,
        "joined_at": iso_datetime(membership.joined_at),
        "last_login_at": iso_datetime(user.last_login_at) if user.last_login_at else None,
        "created_at": iso_datetime(membership.created_at),
        "updated_at": iso_datetime(membership.updated_at),
    }


def _ensure_own_tenant(context: RequestContext, tenant_id: uuid.UUID) -> None:
    if tenant_id != context.tenant_id:
        raise ApiError(403, "TENANT_ACCESS_DENIED", "cannot access another tenant")


async def _get_membership(
    session: AsyncSession, tenant_id: uuid.UUID, membership_id: uuid.UUID
) -> TenantMembership:
    membership = await session.scalar(
        select(TenantMembership)
        .where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.id == membership_id,
        )
        .with_for_update()
    )
    if membership is None:
        raise ApiError(404, "MEMBER_NOT_FOUND", "member not found")
    return membership


async def _active_owner_count(
    session: AsyncSession, tenant_id: uuid.UUID, exclude_id: uuid.UUID
) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(TenantMembership)
        .where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.role_code == MemberRole.OWNER.value,
            TenantMembership.status == MembershipStatus.ACTIVE.value,
            TenantMembership.id != exclude_id,
        )
    )
    return int(count or 0)


@router.get("")
async def list_members(
    tenant_id: uuid.UUID,
    context: MemberReadContext,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    q: Annotated[str | None, Query(max_length=100)] = None,
    role_code: MemberRole | None = None,
    status: MembershipStatus | None = None,
) -> dict[str, Any]:
    _ensure_own_tenant(context, tenant_id)
    await set_tenant_context(session, context.tenant_id)

    conditions = [TenantMembership.tenant_id == tenant_id]
    if q is not None:
        pattern = f"%{q.strip()}%"
        conditions.append(or_(User.email.ilike(pattern), User.display_name.ilike(pattern)))
    if role_code is not None:
        conditions.append(TenantMembership.role_code == role_code.value)
    if status is not None:
        conditions.append(TenantMembership.status == status.value)

    base = select(TenantMembership, User).join(User, User.id == TenantMembership.user_id)
    total = await session.scalar(
        select(func.count())
        .select_from(TenantMembership)
        .join(User, User.id == TenantMembership.user_id)
        .where(*conditions)
    )
    rows = (
        await session.execute(
            base.where(*conditions)
            .order_by(TenantMembership.created_at.asc(), TenantMembership.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return envelope(
        [_member_detail(membership, user) for membership, user in rows],
        context,
        page=page,
        page_size=page_size,
        total=int(total or 0),
    )


@router.patch("/{membership_id}")
async def update_member_role(
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
    payload: MemberRoleUpdate,
    request: Request,
    context: MemberUpdateRoleContext,
    session: SessionDep,
) -> dict[str, Any]:
    _ensure_own_tenant(context, tenant_id)
    await set_tenant_context(session, context.tenant_id)

    membership = await _get_membership(session, tenant_id, membership_id)
    user = await session.get(User, membership.user_id)
    if user is None:
        raise ApiError(404, "USER_NOT_FOUND", "user not found")

    new_role = payload.role_code.value
    if membership.role_code == new_role:
        return envelope(_member_detail(membership, user), context)

    if (
        membership.role_code == MemberRole.OWNER.value
        and membership.status == MembershipStatus.ACTIVE.value
        and new_role != MemberRole.OWNER.value
        and await _active_owner_count(session, tenant_id, membership.id) == 0
    ):
        raise ApiError(
            409,
            "LAST_OWNER_PROTECTED",
            "the last active owner cannot be demoted",
        )

    previous_role = membership.role_code
    membership.role_code = new_role
    AuditService(session).record(
        tenant_id=tenant_id,
        actor_id=context.user_id,
        action="member.role.update",
        resource_type="TENANT_MEMBERSHIP",
        resource_id=membership.id,
        request_id=context.request_id,
        ip_hash=client_ip_hash(request),
        metadata={
            "user_id": str(user.id),
            "previous_role": previous_role,
            "role_code": new_role,
        },
    )
    await session.flush()
    await session.refresh(membership)
    await commit_or_rollback(session)
    return envelope(_member_detail(membership, user), context)
