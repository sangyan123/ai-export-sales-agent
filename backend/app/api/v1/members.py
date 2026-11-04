import re
import secrets
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import envelope, iso_datetime
from app.api.deps import RequestContext, SessionDep, require_permission
from app.api.enums import MemberRole, MembershipStatus, MemberStatusUpdate
from app.api.errors import ApiError
from app.audit import AuditService, client_ip_hash
from app.auth.invitations import issue_invitation
from app.core.permissions import Permission
from app.core.security import hash_password
from app.db.session import commit_or_rollback
from app.db.tenant import set_tenant_context
from app.models.auth import AuthRefreshToken
from app.models.invitation import MemberInvitation
from app.models.tenant import TenantMembership, User

router = APIRouter(prefix="/tenants/{tenant_id}/members", tags=["members"])

MemberReadContext = Annotated[RequestContext, Depends(require_permission(Permission.MEMBER_READ))]
MemberUpdateRoleContext = Annotated[
    RequestContext, Depends(require_permission(Permission.MEMBER_UPDATE_ROLE))
]
MemberInviteContext = Annotated[
    RequestContext, Depends(require_permission(Permission.MEMBER_INVITE))
]
MemberUpdateStatusContext = Annotated[
    RequestContext, Depends(require_permission(Permission.MEMBER_UPDATE_STATUS))
]

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class MemberRoleUpdate(BaseModel):
    role_code: MemberRole


class MemberInvitationCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=120)
    role_code: MemberRole

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("invalid email address")
        return normalized

    @field_validator("display_name")
    @classmethod
    def strip_display_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class MemberStatusUpdatePayload(BaseModel):
    status: MemberStatusUpdate


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


def _invitation_detail(
    membership: TenantMembership,
    user: User,
    raw_token: str,
    invitation: MemberInvitation,
) -> dict[str, Any]:
    return {
        "member": _member_detail(membership, user),
        "invitation": {
            "token": raw_token,
            "expires_at": iso_datetime(invitation.expires_at),
        },
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


@router.post("/invitations", status_code=201)
async def create_member_invitation(
    tenant_id: uuid.UUID,
    payload: MemberInvitationCreate,
    request: Request,
    context: MemberInviteContext,
    session: SessionDep,
) -> dict[str, Any]:
    _ensure_own_tenant(context, tenant_id)
    await set_tenant_context(session, context.tenant_id)

    existing_user = await session.scalar(select(User).where(User.email == payload.email))
    reinvited = False
    if existing_user is not None:
        membership = await session.scalar(
            select(TenantMembership)
            .where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.user_id == existing_user.id,
            )
            .with_for_update()
        )
        if membership is None:
            raise ApiError(
                409,
                "EMAIL_ALREADY_REGISTERED",
                "email is already registered to another account",
            )
        if membership.status == MembershipStatus.ACTIVE.value:
            raise ApiError(409, "MEMBER_ALREADY_EXISTS", "member already exists in this tenant")
        if membership.status == MembershipStatus.DISABLED.value:
            raise ApiError(
                409,
                "MEMBER_DISABLED",
                "member is disabled; enable the existing membership instead",
            )
        membership.role_code = payload.role_code.value
        existing_user.display_name = payload.display_name
        user = existing_user
        reinvited = True
    else:
        user = User(
            email=payload.email,
            password_hash=hash_password(secrets.token_urlsafe(48)),
            display_name=payload.display_name,
            status="ACTIVE",
        )
        session.add(user)
        await session.flush()
        membership = TenantMembership(
            tenant_id=tenant_id,
            user_id=user.id,
            role_code=payload.role_code.value,
            status=MembershipStatus.INVITED.value,
        )
        session.add(membership)
        await session.flush()

    raw_token, invitation = await issue_invitation(
        session,
        tenant_id=tenant_id,
        membership_id=membership.id,
        user_id=user.id,
        created_by_id=context.user_id,
    )
    AuditService(session).record(
        tenant_id=tenant_id,
        actor_id=context.user_id,
        action="member.invite",
        resource_type="TENANT_MEMBERSHIP",
        resource_id=membership.id,
        request_id=context.request_id,
        ip_hash=client_ip_hash(request),
        metadata={
            "user_id": str(user.id),
            "email": user.email,
            "role_code": membership.role_code,
            "reinvited": reinvited,
        },
    )
    await session.flush()
    await session.refresh(membership)
    await commit_or_rollback(session)
    return envelope(_invitation_detail(membership, user, raw_token, invitation), context)


@router.post("/{membership_id}/invitations")
async def resend_member_invitation(
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
    request: Request,
    context: MemberInviteContext,
    session: SessionDep,
) -> dict[str, Any]:
    _ensure_own_tenant(context, tenant_id)
    await set_tenant_context(session, context.tenant_id)

    membership = await _get_membership(session, tenant_id, membership_id)
    if membership.status != MembershipStatus.INVITED.value:
        raise ApiError(409, "INVITATION_NOT_PENDING", "member is not awaiting invitation")
    user = await session.get(User, membership.user_id)
    if user is None:
        raise ApiError(404, "USER_NOT_FOUND", "user not found")

    raw_token, invitation = await issue_invitation(
        session,
        tenant_id=tenant_id,
        membership_id=membership.id,
        user_id=user.id,
        created_by_id=context.user_id,
    )
    AuditService(session).record(
        tenant_id=tenant_id,
        actor_id=context.user_id,
        action="member.invite.resend",
        resource_type="TENANT_MEMBERSHIP",
        resource_id=membership.id,
        request_id=context.request_id,
        ip_hash=client_ip_hash(request),
        metadata={
            "user_id": str(user.id),
            "email": user.email,
            "role_code": membership.role_code,
        },
    )
    await session.flush()
    await commit_or_rollback(session)
    return envelope(_invitation_detail(membership, user, raw_token, invitation), context)


@router.delete("/{membership_id}/invitations")
async def cancel_member_invitation(
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
    request: Request,
    context: MemberInviteContext,
    session: SessionDep,
) -> dict[str, Any]:
    _ensure_own_tenant(context, tenant_id)
    await set_tenant_context(session, context.tenant_id)

    membership = await _get_membership(session, tenant_id, membership_id)
    if membership.status != MembershipStatus.INVITED.value:
        raise ApiError(409, "INVITATION_NOT_PENDING", "member is not awaiting invitation")
    pending = await session.scalar(
        select(MemberInvitation).where(
            MemberInvitation.membership_id == membership.id,
            MemberInvitation.accepted_at.is_(None),
            MemberInvitation.revoked_at.is_(None),
        )
    )
    if pending is None:
        raise ApiError(409, "INVITATION_NOT_PENDING", "member has no pending invitation")

    user = await session.get(User, membership.user_id)
    AuditService(session).record(
        tenant_id=tenant_id,
        actor_id=context.user_id,
        action="member.invite.cancel",
        resource_type="TENANT_MEMBERSHIP",
        resource_id=membership.id,
        request_id=context.request_id,
        ip_hash=client_ip_hash(request),
        metadata={
            "user_id": str(membership.user_id),
            "email": user.email if user else None,
            "role_code": membership.role_code,
        },
    )
    await session.delete(membership)
    if user is not None:
        await session.delete(user)
    await session.flush()
    await commit_or_rollback(session)
    return envelope({"cancelled": True, "membership_id": str(membership_id)}, context)


@router.patch("/{membership_id}/status")
async def update_member_status(
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
    payload: MemberStatusUpdatePayload,
    request: Request,
    context: MemberUpdateStatusContext,
    session: SessionDep,
) -> dict[str, Any]:
    _ensure_own_tenant(context, tenant_id)
    await set_tenant_context(session, context.tenant_id)

    membership = await _get_membership(session, tenant_id, membership_id)
    user = await session.get(User, membership.user_id)
    if user is None:
        raise ApiError(404, "USER_NOT_FOUND", "user not found")

    if membership.status == MembershipStatus.INVITED.value:
        raise ApiError(
            409,
            "INVITATION_NOT_ACCEPTED",
            "invitation has not been accepted; resend or cancel it instead",
        )

    new_status = payload.status.value
    if membership.status == new_status:
        return envelope(_member_detail(membership, user), context)

    now = datetime.now(UTC)
    if new_status == MembershipStatus.DISABLED.value:
        if membership.id == context.membership_id:
            raise ApiError(409, "SELF_DISABLE_NOT_ALLOWED", "cannot disable the current account")
        if (
            membership.role_code == MemberRole.OWNER.value
            and await _active_owner_count(session, tenant_id, membership.id) == 0
        ):
            raise ApiError(
                409,
                "LAST_OWNER_PROTECTED",
                "the last active owner cannot be disabled",
            )
        await session.execute(
            update(AuthRefreshToken)
            .where(
                AuthRefreshToken.user_id == membership.user_id,
                AuthRefreshToken.tenant_id == tenant_id,
                AuthRefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        action = "member.disable"
    else:
        action = "member.enable"

    previous_status = membership.status
    membership.status = new_status
    AuditService(session).record(
        tenant_id=tenant_id,
        actor_id=context.user_id,
        action=action,
        resource_type="TENANT_MEMBERSHIP",
        resource_id=membership.id,
        request_id=context.request_id,
        ip_hash=client_ip_hash(request),
        metadata={
            "user_id": str(user.id),
            "email": user.email,
            "previous_status": previous_status,
            "status": new_status,
        },
    )
    await session.flush()
    await session.refresh(membership)
    await commit_or_rollback(session)
    return envelope(_member_detail(membership, user), context)
