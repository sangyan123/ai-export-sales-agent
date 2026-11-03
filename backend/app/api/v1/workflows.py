import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.common import envelope, iso_datetime
from app.api.deps import RequestContext, SessionDep, require_permission
from app.audit import AuditService, client_ip_hash
from app.core.permissions import Permission
from app.db.session import commit_or_rollback
from app.models.workflow import WorkflowRun
from app.workflows.service import WorkflowRunService

router = APIRouter(prefix="/workflow-runs", tags=["workflows"])

WorkflowReadContext = Annotated[
    RequestContext, Depends(require_permission(Permission.WORKFLOW_READ))
]
WorkflowCancelContext = Annotated[
    RequestContext, Depends(require_permission(Permission.WORKFLOW_CANCEL))
]


class CancelWorkflowRunRequest(BaseModel):
    note: str | None = Field(default=None, max_length=4000)


def _workflow_run(run: WorkflowRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "workflow_type": run.workflow_type,
        "business_object_type": run.business_object_type,
        "business_object_id": str(run.business_object_id),
        "status": run.status,
        "error_code": run.error_code,
        "started_at": iso_datetime(run.started_at) if run.started_at else None,
        "finished_at": iso_datetime(run.finished_at) if run.finished_at else None,
        "created_at": iso_datetime(run.created_at),
        "updated_at": iso_datetime(run.updated_at),
    }


@router.get("/{run_id}")
async def get_workflow_run(
    run_id: uuid.UUID,
    context: WorkflowReadContext,
    session: SessionDep,
) -> dict[str, Any]:
    run = await WorkflowRunService(session).get(
        tenant_id=context.tenant_id,
        run_id=run_id,
    )
    return envelope(_workflow_run(run), context)


@router.post("/{run_id}/cancel")
async def cancel_workflow_run(
    run_id: uuid.UUID,
    context: WorkflowCancelContext,
    session: SessionDep,
    request: Request,
    payload: CancelWorkflowRunRequest | None = None,
) -> dict[str, Any]:
    note = payload.note if payload else None
    run, previous_status = await WorkflowRunService(session).cancel(
        tenant_id=context.tenant_id,
        run_id=run_id,
    )
    AuditService(session).record(
        tenant_id=context.tenant_id,
        actor_id=context.user_id,
        action="workflow.cancel",
        resource_type="WORKFLOW_RUN",
        resource_id=run.id,
        request_id=context.request_id,
        ip_hash=client_ip_hash(request),
        metadata={
            "workflow_type": run.workflow_type,
            "business_object_type": run.business_object_type,
            "business_object_id": str(run.business_object_id),
            "previous_status": previous_status,
            "note": note,
        },
    )
    await commit_or_rollback(session)
    return envelope(_workflow_run(run), context)
