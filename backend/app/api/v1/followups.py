import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import envelope, iso_datetime
from app.api.deps import RequestContext, SessionDep, require_permission
from app.api.enums import FollowupStatus
from app.api.errors import ApiError
from app.audit import AuditService, client_ip_hash
from app.core.permissions import Permission
from app.db.session import commit_or_rollback
from app.db.tenant import set_tenant_context
from app.models.customer import Customer
from app.models.followup import FollowupTask
from app.models.inquiry import Inquiry
from app.models.tenant import TenantMembership

router = APIRouter(tags=["followups"])

FollowupReadContext = Annotated[
    RequestContext, Depends(require_permission(Permission.FOLLOWUP_READ))
]
FollowupCreateContext = Annotated[
    RequestContext, Depends(require_permission(Permission.FOLLOWUP_CREATE))
]
FollowupUpdateContext = Annotated[
    RequestContext, Depends(require_permission(Permission.FOLLOWUP_UPDATE))
]

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "PENDING": frozenset({"DONE", "CANCELLED"}),
    "DONE": frozenset({"PENDING"}),
    "CANCELLED": frozenset({"PENDING"}),
}


class FollowupCreate(BaseModel):
    customer_id: uuid.UUID
    inquiry_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=240)
    due_at: datetime
    assigned_to: uuid.UUID | None = None

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("due_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("due_at must include a timezone offset")
        return value


class FollowupUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=240)
    due_at: datetime | None = None
    assigned_to: uuid.UUID | None = None
    status: FollowupStatus | None = None

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("due_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("due_at must include a timezone offset")
        return value

    @model_validator(mode="after")
    def require_change(self) -> "FollowupUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        return self


def _followup_detail(task: FollowupTask) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "customer_id": str(task.customer_id),
        "inquiry_id": str(task.inquiry_id) if task.inquiry_id else None,
        "title": task.title,
        "due_at": iso_datetime(task.due_at),
        "assigned_to": str(task.assigned_to) if task.assigned_to else None,
        "status": task.status,
        "source": task.source,
        "completed_at": iso_datetime(task.completed_at) if task.completed_at else None,
        "created_at": iso_datetime(task.created_at),
        "updated_at": iso_datetime(task.updated_at),
    }


async def _get_task(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    task_id: uuid.UUID,
) -> FollowupTask:
    await set_tenant_context(session, tenant_id)
    task = await session.scalar(
        select(FollowupTask).where(
            FollowupTask.tenant_id == tenant_id,
            FollowupTask.id == task_id,
        )
    )
    if task is None:
        raise ApiError(404, "FOLLOWUP_NOT_FOUND", "followup task not found")
    return task


async def _ensure_customer(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> None:
    exists = await session.scalar(
        select(Customer.id).where(
            Customer.tenant_id == tenant_id,
            Customer.id == customer_id,
        )
    )
    if exists is None:
        raise ApiError(404, "CUSTOMER_NOT_FOUND", "customer not found")


async def _ensure_inquiry_customer(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    inquiry_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> None:
    inquiry = await session.scalar(
        select(Inquiry).where(
            Inquiry.tenant_id == tenant_id,
            Inquiry.id == inquiry_id,
        )
    )
    if inquiry is None:
        raise ApiError(404, "INQUIRY_NOT_FOUND", "inquiry not found")
    if inquiry.customer_id != customer_id:
        raise ApiError(
            400,
            "FOLLOWUP_CUSTOMER_MISMATCH",
            "inquiry does not belong to the given customer",
        )


async def _ensure_assignee_member(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
) -> None:
    if user_id is None:
        return
    membership_id = await session.scalar(
        select(TenantMembership.id).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user_id,
            TenantMembership.status == "ACTIVE",
        )
    )
    if membership_id is None:
        raise ApiError(400, "ASSIGNEE_NOT_MEMBER", "assignee is not an active tenant member")


@router.get("/followups")
async def list_followups(
    context: FollowupReadContext,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[FollowupStatus | None, Query(alias="status")] = None,
    assigned_to: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    inquiry_id: uuid.UUID | None = None,
    overdue: bool = False,
) -> dict[str, Any]:
    await set_tenant_context(session, context.tenant_id)
    conditions = [FollowupTask.tenant_id == context.tenant_id]
    if status_filter is not None:
        conditions.append(FollowupTask.status == status_filter.value)
    if assigned_to is not None:
        conditions.append(FollowupTask.assigned_to == assigned_to)
    if customer_id is not None:
        conditions.append(FollowupTask.customer_id == customer_id)
    if inquiry_id is not None:
        conditions.append(FollowupTask.inquiry_id == inquiry_id)
    if overdue:
        conditions.append(FollowupTask.status == FollowupStatus.PENDING.value)
        conditions.append(FollowupTask.due_at < datetime.now(UTC))

    total = await session.scalar(select(func.count()).select_from(FollowupTask).where(*conditions))
    tasks = list(
        await session.scalars(
            select(FollowupTask)
            .where(*conditions)
            .order_by(FollowupTask.due_at, FollowupTask.created_at)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return envelope(
        [_followup_detail(task) for task in tasks],
        context,
        page=page,
        page_size=page_size,
        total=int(total or 0),
    )


@router.post("/followups", status_code=status.HTTP_201_CREATED)
async def create_followup(
    payload: FollowupCreate,
    context: FollowupCreateContext,
    session: SessionDep,
    request: Request,
) -> dict[str, Any]:
    await set_tenant_context(session, context.tenant_id)
    await _ensure_customer(session, context.tenant_id, payload.customer_id)
    if payload.inquiry_id is not None:
        await _ensure_inquiry_customer(
            session,
            context.tenant_id,
            payload.inquiry_id,
            payload.customer_id,
        )
    assigned_to = payload.assigned_to or context.user_id
    await _ensure_assignee_member(session, context.tenant_id, assigned_to)

    task = FollowupTask(
        tenant_id=context.tenant_id,
        customer_id=payload.customer_id,
        inquiry_id=payload.inquiry_id,
        title=payload.title,
        due_at=payload.due_at,
        assigned_to=assigned_to,
        status=FollowupStatus.PENDING.value,
        source="MANUAL",
    )
    session.add(task)
    await session.flush()
    AuditService(session).record(
        tenant_id=context.tenant_id,
        actor_id=context.user_id,
        action="followup.create",
        resource_type="FOLLOWUP",
        resource_id=task.id,
        request_id=context.request_id,
        ip_hash=client_ip_hash(request),
        metadata={
            "customer_id": str(task.customer_id),
            "inquiry_id": str(task.inquiry_id) if task.inquiry_id else None,
            "assigned_to": str(task.assigned_to) if task.assigned_to else None,
            "due_at": iso_datetime(task.due_at),
        },
    )
    await session.refresh(task)
    await commit_or_rollback(session)
    return envelope(_followup_detail(task), context)


@router.patch("/followups/{task_id}")
async def update_followup(
    task_id: uuid.UUID,
    payload: FollowupUpdate,
    context: FollowupUpdateContext,
    session: SessionDep,
    request: Request,
) -> dict[str, Any]:
    task = await _get_task(session, context.tenant_id, task_id)
    data = payload.model_dump(exclude_unset=True)
    for field in ("title", "due_at", "status"):
        if field in data and data[field] is None:
            raise ApiError(422, "VALIDATION_ERROR", f"{field} cannot be null")

    new_status = data.pop("status", None)
    if new_status is not None:
        new_status = FollowupStatus(new_status).value
        if new_status != task.status:
            if new_status not in ALLOWED_TRANSITIONS[task.status]:
                raise ApiError(
                    409,
                    "INVALID_STATUS_TRANSITION",
                    f"cannot change followup from {task.status} to {new_status}",
                )
            task.completed_at = datetime.now(UTC) if new_status == "DONE" else None
            task.status = new_status

    if "assigned_to" in data:
        await _ensure_assignee_member(
            session,
            context.tenant_id,
            data["assigned_to"],
        )
    for field, value in data.items():
        setattr(task, field, value)

    await session.flush()
    AuditService(session).record(
        tenant_id=context.tenant_id,
        actor_id=context.user_id,
        action="followup.update",
        resource_type="FOLLOWUP",
        resource_id=task.id,
        request_id=context.request_id,
        ip_hash=client_ip_hash(request),
        metadata={
            "fields": sorted([*data.keys(), *(("status",) if new_status else ())]),
            "status": task.status,
        },
    )
    await session.refresh(task)
    await commit_or_rollback(session)
    return envelope(_followup_detail(task), context)
