import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.common import envelope, iso_datetime
from app.api.deps import RequestContext, SessionDep, require_permission
from app.core.permissions import Permission
from app.db.tenant import set_tenant_context
from app.models.audit import AuditLog

router = APIRouter(prefix="/audit-logs", tags=["audit"])

AuditReadContext = Annotated[RequestContext, Depends(require_permission(Permission.AUDIT_READ))]


def _audit_log(entry: AuditLog) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "actor_id": str(entry.actor_id) if entry.actor_id else None,
        "action": entry.action,
        "resource_type": entry.resource_type,
        "resource_id": str(entry.resource_id) if entry.resource_id else None,
        "request_id": entry.request_id,
        "ip_hash": entry.ip_hash,
        "metadata": entry.metadata_json,
        "created_at": iso_datetime(entry.created_at),
    }


@router.get("")
async def list_audit_logs(
    context: AuditReadContext,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    action: Annotated[str | None, Query(max_length=80)] = None,
    resource_type: Annotated[str | None, Query(max_length=60)] = None,
    resource_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> dict[str, Any]:
    await set_tenant_context(session, context.tenant_id)
    if created_from is not None and created_from.tzinfo is None:
        created_from = created_from.replace(tzinfo=UTC)
    if created_to is not None and created_to.tzinfo is None:
        created_to = created_to.replace(tzinfo=UTC)
    conditions = [AuditLog.tenant_id == context.tenant_id]
    if action is not None:
        conditions.append(AuditLog.action == action)
    if resource_type is not None:
        conditions.append(AuditLog.resource_type == resource_type)
    if resource_id is not None:
        conditions.append(AuditLog.resource_id == resource_id)
    if actor_id is not None:
        conditions.append(AuditLog.actor_id == actor_id)
    if created_from is not None:
        conditions.append(AuditLog.created_at >= created_from)
    if created_to is not None:
        conditions.append(AuditLog.created_at <= created_to)

    total = await session.scalar(select(func.count()).select_from(AuditLog).where(*conditions))
    entries = list(
        await session.scalars(
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return envelope(
        [_audit_log(entry) for entry in entries],
        context,
        page=page,
        page_size=page_size,
        total=int(total or 0),
    )
