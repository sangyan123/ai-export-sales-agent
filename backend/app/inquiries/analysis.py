import logging
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import InquiryParser, InquiryParseResult, ParserError, get_inquiry_parser
from app.ai.usage import LLMUsage
from app.audit import AuditService
from app.core.config import settings
from app.db.session import SessionFactory
from app.db.tenant import set_tenant_context
from app.inquiries import InquiryStatus
from app.models.ai_provider import TenantAIProviderConfig
from app.models.ai_usage import AIUsageRecord
from app.models.inquiry import Inquiry, InquiryRequirement
from app.models.workflow import WorkflowRun
from app.workflows import WorkflowStatus

logger = logging.getLogger(__name__)

WORKFLOW_TYPE = "INQUIRY_ANALYSIS"
BUSINESS_OBJECT_TYPE = "INQUIRY"
ANALYZABLE_STATUSES = frozenset({InquiryStatus.RECEIVED, InquiryStatus.NEEDS_INFO})
ACTIVE_STATUSES = (WorkflowStatus.QUEUED.value, WorkflowStatus.RUNNING.value)


class AnalysisErrorCode(StrEnum):
    INQUIRY_NOT_FOUND = "INQUIRY_NOT_FOUND"
    INQUIRY_STATUS_NOT_ANALYZABLE = "INQUIRY_STATUS_NOT_ANALYZABLE"
    INQUIRY_ANALYSIS_IN_PROGRESS = "INQUIRY_ANALYSIS_IN_PROGRESS"
    ANALYSIS_RUN_NOT_FOUND = "ANALYSIS_RUN_NOT_FOUND"


class AnalysisError(Exception):
    def __init__(self, code: AnalysisErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class InquiryAnalysisService:
    def __init__(self, session: AsyncSession, parser: InquiryParser | None = None) -> None:
        self._session = session
        self._parser = parser

    async def enqueue(
        self,
        *,
        tenant_id: uuid.UUID,
        inquiry_id: uuid.UUID,
        requested_by: uuid.UUID,
        request_id: str | None = None,
    ) -> WorkflowRun:
        await set_tenant_context(self._session, tenant_id)
        inquiry = await self._session.scalar(
            select(Inquiry)
            .where(Inquiry.tenant_id == tenant_id, Inquiry.id == inquiry_id)
            .with_for_update()
        )
        if inquiry is None:
            raise AnalysisError(AnalysisErrorCode.INQUIRY_NOT_FOUND, "inquiry not found")

        active_run_id = await self._session.scalar(
            select(WorkflowRun.id).where(
                WorkflowRun.tenant_id == tenant_id,
                WorkflowRun.workflow_type == WORKFLOW_TYPE,
                WorkflowRun.business_object_type == BUSINESS_OBJECT_TYPE,
                WorkflowRun.business_object_id == inquiry_id,
                WorkflowRun.status.in_(ACTIVE_STATUSES),
            )
        )
        if active_run_id is not None:
            raise AnalysisError(
                AnalysisErrorCode.INQUIRY_ANALYSIS_IN_PROGRESS,
                "an analysis run is already active for this inquiry",
            )
        if inquiry.status not in ANALYZABLE_STATUSES:
            raise AnalysisError(
                AnalysisErrorCode.INQUIRY_STATUS_NOT_ANALYZABLE,
                f"inquiry status {inquiry.status} cannot start analysis",
            )

        run = WorkflowRun(
            tenant_id=tenant_id,
            workflow_type=WORKFLOW_TYPE,
            business_object_type=BUSINESS_OBJECT_TYPE,
            business_object_id=inquiry_id,
            status=WorkflowStatus.QUEUED.value,
            input_ref={"inquiry_id": str(inquiry_id), "request_id": request_id},
            requested_by=requested_by,
        )
        self._session.add(run)
        inquiry.status = InquiryStatus.PARSING.value
        await self._session.flush()
        await self._session.refresh(run)
        return run

    async def execute(self, *, tenant_id: uuid.UUID, run_id: uuid.UUID) -> WorkflowRun | None:
        run = await self._begin(tenant_id, run_id)
        if run is None:
            return None
        if run.status != WorkflowStatus.RUNNING.value:
            return run

        input_ref = run.input_ref or {}
        subject = str(input_ref.get("subject") or "")
        raw_text = str(input_ref.get("raw_text") or "")
        language = input_ref.get("language")
        if language is not None:
            language = str(language)

        captured: list[LLMUsage] = []

        async def usage_sink(usage: LLMUsage) -> None:
            captured.append(usage)

        try:
            tenant_config = await self._session.scalar(
                select(TenantAIProviderConfig).where(
                    TenantAIProviderConfig.tenant_id == tenant_id
                )
            )
            parser = self._parser or get_inquiry_parser(tenant_config)
            result = await parser.parse(
                subject=subject,
                raw_text=raw_text,
                language=language,
                usage_sink=usage_sink,
            )
        except ParserError as exc:
            logger.warning("inquiry analysis %s failed: %s", run_id, exc.message)
            return await self._fail(tenant_id, run_id, exc.code, exc.message)
        except Exception:
            logger.exception("inquiry analysis %s raised an unexpected error", run_id)
            return await self._fail(
                tenant_id, run_id, "ANALYSIS_FAILED", "unexpected analysis failure"
            )

        if captured:
            usage = captured[-1]
            self._session.add(
                AIUsageRecord(
                    tenant_id=tenant_id,
                    workflow_run_id=run_id,
                    operation_type="INQUIRY_PARSE",
                    model_id=usage.model_id,
                    provider=settings.llm_provider or "deterministic",
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    total_tokens=usage.total_tokens,
                    duration_ms=usage.duration_ms,
                    status="SUCCESS",
                    requested_by_id=run.requested_by,
                    finished_at=datetime.now(UTC),
                )
            )

        return await self._complete(
            tenant_id=tenant_id,
            run_id=run_id,
            result=result,
            model_id=parser.model_id,
        )

    async def _begin(self, tenant_id: uuid.UUID, run_id: uuid.UUID) -> WorkflowRun | None:
        await set_tenant_context(self._session, tenant_id)
        run = await self._lock_run(tenant_id, run_id)
        if run is None:
            return None

        if run.status == WorkflowStatus.CANCELLED.value:
            await self._revert_parsing(tenant_id, run)
            return run
        if run.status != WorkflowStatus.QUEUED.value:
            return run

        inquiry = await self._lock_inquiry(tenant_id, run.business_object_id)
        if inquiry is None:
            return await self._mark_failed(
                run, None, "ANALYSIS_INQUIRY_MISSING", "inquiry no longer exists"
            )

        if inquiry.status != InquiryStatus.PARSING.value:
            inquiry.status = InquiryStatus.PARSING.value

        input_ref = {
            "inquiry_id": str(inquiry.id),
            "subject": inquiry.subject,
            "raw_text": inquiry.raw_body or "",
            "language": inquiry.language,
            "request_id": (run.input_ref or {}).get("request_id"),
        }
        run.input_ref = input_ref
        run.status = WorkflowStatus.RUNNING.value
        run.started_at = datetime.now(UTC)
        await self._session.flush()
        await self._session.refresh(run)
        await self._session.commit()
        return run

    async def _complete(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        result: InquiryParseResult,
        model_id: str,
    ) -> WorkflowRun | None:
        await set_tenant_context(self._session, tenant_id)
        run = await self._lock_run(tenant_id, run_id)
        if run is None:
            return None

        inquiry = await self._lock_inquiry(tenant_id, run.business_object_id)
        if run.status == WorkflowStatus.CANCELLED.value:
            await self._revert_parsing(tenant_id, run, inquiry)
            return run
        if run.status != WorkflowStatus.RUNNING.value or inquiry is None:
            await self._session.commit()
            return run

        latest_version = await self._session.scalar(
            select(func.max(InquiryRequirement.schema_version)).where(
                InquiryRequirement.tenant_id == tenant_id,
                InquiryRequirement.inquiry_id == inquiry.id,
            )
        )
        schema_version = int(latest_version or 0) + 1
        requirement = InquiryRequirement(
            tenant_id=tenant_id,
            inquiry_id=inquiry.id,
            schema_version=schema_version,
            parsed_json=result.model_dump(mode="json"),
            confirmed_json={},
            confidence_json=result.confidence_map(),
            evidence_json=result.evidence_map(),
            model_id=model_id,
        )
        self._session.add(requirement)

        critical_missing = result.critical_missing_fields()
        inquiry.status = (
            InquiryStatus.NEEDS_INFO.value
            if critical_missing
            else InquiryStatus.READY_FOR_MATCH.value
        )
        run.status = WorkflowStatus.SUCCEEDED.value
        run.finished_at = datetime.now(UTC)
        run.output_ref = {
            "schema_version": schema_version,
            "overall_confidence": result.overall_confidence,
            "missing_fields": result.missing_field_names(),
            "critical_missing_fields": critical_missing,
        }
        self._record_audit(
            run,
            "inquiry.analysis.completed",
            {
                "workflow_run_id": str(run.id),
                "schema_version": schema_version,
                "overall_confidence": result.overall_confidence,
                "missing_fields": result.missing_field_names(),
            },
        )
        await self._session.flush()
        await self._session.refresh(run)
        await self._session.commit()
        return run

    async def _fail(
        self,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        error_code: str,
        message: str,
    ) -> WorkflowRun | None:
        await set_tenant_context(self._session, tenant_id)
        run = await self._lock_run(tenant_id, run_id)
        if run is None:
            return None
        if run.status == WorkflowStatus.CANCELLED.value:
            await self._revert_parsing(tenant_id, run)
            return run
        if run.status != WorkflowStatus.RUNNING.value:
            return run

        inquiry = await self._lock_inquiry(tenant_id, run.business_object_id)
        return await self._mark_failed(run, inquiry, error_code, message)

    async def _mark_failed(
        self,
        run: WorkflowRun,
        inquiry: Inquiry | None,
        error_code: str,
        message: str,
    ) -> WorkflowRun:
        if inquiry is not None and inquiry.status == InquiryStatus.PARSING.value:
            inquiry.status = InquiryStatus.NEEDS_INFO.value
        run.status = WorkflowStatus.FAILED.value
        run.finished_at = datetime.now(UTC)
        run.error_code = error_code[:80]
        run.output_ref = {"error": message[:500]}
        self._record_audit(
            run,
            "inquiry.analysis.failed",
            {"workflow_run_id": str(run.id), "error_code": run.error_code},
        )
        await self._session.flush()
        await self._session.refresh(run)
        await self._session.commit()
        return run

    async def _revert_parsing(
        self,
        tenant_id: uuid.UUID,
        run: WorkflowRun,
        inquiry: Inquiry | None = None,
    ) -> None:
        if inquiry is None:
            inquiry = await self._lock_inquiry(tenant_id, run.business_object_id)
        if inquiry is not None and inquiry.status == InquiryStatus.PARSING.value:
            inquiry.status = InquiryStatus.NEEDS_INFO.value
        await self._session.flush()
        await self._session.commit()

    async def _lock_run(self, tenant_id: uuid.UUID, run_id: uuid.UUID) -> WorkflowRun | None:
        return await self._session.scalar(
            select(WorkflowRun)
            .where(WorkflowRun.tenant_id == tenant_id, WorkflowRun.id == run_id)
            .with_for_update()
        )

    async def _lock_inquiry(self, tenant_id: uuid.UUID, inquiry_id: uuid.UUID) -> Inquiry | None:
        return await self._session.scalar(
            select(Inquiry)
            .where(Inquiry.tenant_id == tenant_id, Inquiry.id == inquiry_id)
            .with_for_update()
        )

    def _record_audit(
        self, run: WorkflowRun, action: str, metadata: dict[str, Any] | None = None
    ) -> None:
        input_ref = run.input_ref or {}
        AuditService(self._session).record(
            tenant_id=run.tenant_id,
            actor_id=run.requested_by,
            action=action,
            resource_type="INQUIRY",
            resource_id=run.business_object_id,
            request_id=input_ref.get("request_id"),
            metadata=metadata,
        )


async def run_inquiry_analysis(*, tenant_id: uuid.UUID, run_id: uuid.UUID) -> None:
    """Background entry point executing a queued analysis run with its own session."""
    async with SessionFactory() as session:
        service = InquiryAnalysisService(session)
        try:
            await service.execute(tenant_id=tenant_id, run_id=run_id)
        except Exception:
            logger.exception("inquiry analysis background run %s crashed", run_id)
            await session.rollback()


__all__ = [
    "AnalysisError",
    "AnalysisErrorCode",
    "InquiryAnalysisService",
    "run_inquiry_analysis",
]
