import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import envelope, iso_datetime
from app.api.deps import RequestContext, SessionDep, require_permission
from app.api.errors import ApiError
from app.core.permissions import Permission
from app.models.ai_usage import AIUsageRecord

router = APIRouter(tags=["usage"])

UsageReadContext = Annotated[
    RequestContext, Depends(require_permission(Permission.USAGE_READ))
]


def _record_detail(record: AIUsageRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "workflow_run_id": str(record.workflow_run_id) if record.workflow_run_id else None,
        "operation_type": record.operation_type,
        "model_id": record.model_id,
        "provider": record.provider,
        "prompt_tokens": record.prompt_tokens,
        "completion_tokens": record.completion_tokens,
        "total_tokens": record.total_tokens,
        "duration_ms": record.duration_ms,
        "status": record.status,
        "error_code": record.error_code,
        "requested_by": str(record.requested_by) if record.requested_by else None,
        "finished_at": iso_datetime(record.finished_at) if record.finished_at else None,
        "created_at": iso_datetime(record.created_at),
    }


@router.get("/usage/summary")
async def usage_summary(
    context: UsageReadContext,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)
    conditions = [
        AIUsageRecord.tenant_id == context.tenant_id,
        AIUsageRecord.created_at >= since,
    ]

    totals = await session.execute(
        select(
            func.count().label("call_count"),
            func.coalesce(func.sum(AIUsageRecord.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(AIUsageRecord.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(AIUsageRecord.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(AIUsageRecord.duration_ms), 0).label("duration_ms"),
        ).where(*conditions)
    )
    row = totals.one()

    by_operation_rows = await session.execute(
        select(
            AIUsageRecord.operation_type,
            func.count().label("call_count"),
            func.coalesce(func.sum(AIUsageRecord.total_tokens), 0).label("total_tokens"),
        )
        .where(*conditions)
        .group_by(AIUsageRecord.operation_type)
    )
    by_operation: dict[str, dict[str, int]] = {}
    for op_row in by_operation_rows:
        by_operation[op_row.operation_type] = {
            "call_count": int(op_row.call_count),
            "total_tokens": int(op_row.total_tokens),
        }

    return envelope(
        {
            "period_days": days,
            "call_count": int(row.call_count),
            "prompt_tokens": int(row.prompt_tokens),
            "completion_tokens": int(row.completion_tokens),
            "total_tokens": int(row.total_tokens),
            "total_duration_ms": int(row.duration_ms),
            "by_operation": by_operation,
        },
        context,
    )


@router.get("/usage/records")
async def usage_records(
    context: UsageReadContext,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    operation_type: str | None = None,
) -> dict[str, Any]:
    conditions = [AIUsageRecord.tenant_id == context.tenant_id]
    if operation_type:
        if operation_type not in {"INQUIRY_PARSE", "EMAIL_GENERATE"}:
            raise ApiError(422, "VALIDATION_ERROR", f"unknown operation_type: {operation_type}")
        conditions.append(AIUsageRecord.operation_type == operation_type)

    total = await session.scalar(
        select(func.count()).select_from(AIUsageRecord).where(*conditions)
    )
    records = list(
        await session.scalars(
            select(AIUsageRecord)
            .where(*conditions)
            .order_by(AIUsageRecord.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return envelope(
        [_record_detail(record) for record in records],
        context,
        page=page,
        page_size=page_size,
        total=int(total or 0),
    )
