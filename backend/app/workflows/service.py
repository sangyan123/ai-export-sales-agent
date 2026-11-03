import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tenant import set_tenant_context
from app.models.workflow import WorkflowRun
from app.workflows import (
    CANCELLABLE_STATUSES,
    WorkflowError,
    WorkflowErrorCode,
    WorkflowStatus,
)


class WorkflowRunService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, *, tenant_id: uuid.UUID, run_id: uuid.UUID, for_update: bool = False
    ) -> WorkflowRun:
        await set_tenant_context(self._session, tenant_id)
        statement = select(WorkflowRun).where(
            WorkflowRun.tenant_id == tenant_id,
            WorkflowRun.id == run_id,
        )
        if for_update:
            statement = statement.with_for_update()
        run = await self._session.scalar(statement)
        if run is None:
            raise WorkflowError(
                WorkflowErrorCode.WORKFLOW_RUN_NOT_FOUND,
                "workflow run not found",
            )
        return run

    async def cancel(self, *, tenant_id: uuid.UUID, run_id: uuid.UUID) -> tuple[WorkflowRun, str]:
        run = await self.get(tenant_id=tenant_id, run_id=run_id, for_update=True)
        previous_status = run.status
        if previous_status not in {status.value for status in CANCELLABLE_STATUSES}:
            raise WorkflowError(
                WorkflowErrorCode.INVALID_WORKFLOW_STATUS,
                f"workflow run status {previous_status} cannot be cancelled",
            )
        run.status = WorkflowStatus.CANCELLED.value
        run.finished_at = datetime.now(UTC)
        await self._session.flush()
        await self._session.refresh(run)
        return run, previous_status
