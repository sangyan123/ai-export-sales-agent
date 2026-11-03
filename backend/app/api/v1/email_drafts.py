import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field, field_validator, model_validator

from app.api.common import envelope, iso_datetime
from app.api.deps import RequestContext, SessionDep, require_permission
from app.audit import AuditService, client_ip_hash
from app.core.permissions import Permission
from app.db.session import commit_or_rollback
from app.email.service import EmailDraftService
from app.models.email import EmailDraft

router = APIRouter(tags=["email-drafts"])

EmailDraftContext = Annotated[RequestContext, Depends(require_permission(Permission.EMAIL_DRAFT))]
EmailReadContext = Annotated[RequestContext, Depends(require_permission(Permission.EMAIL_READ))]
EmailUpdateContext = Annotated[RequestContext, Depends(require_permission(Permission.EMAIL_UPDATE))]
EmailApproveContext = Annotated[
    RequestContext, Depends(require_permission(Permission.EMAIL_APPROVE))
]


class EmailDraftCreate(BaseModel):
    quote_id: uuid.UUID | None = None
    language: str = Field(default="en", pattern=r"^[A-Za-z]{2}(?:-[A-Za-z]{2})?$")


class EmailDraftUpdate(BaseModel):
    subject: str | None = Field(default=None, min_length=1, max_length=240)
    body: str | None = Field(default=None, min_length=1)

    @field_validator("subject", "body")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @model_validator(mode="after")
    def require_change(self) -> "EmailDraftUpdate":
        if self.subject is None and self.body is None:
            raise ValueError("subject or body is required")
        return self


def _draft_detail(draft: EmailDraft) -> dict[str, Any]:
    return {
        "id": str(draft.id),
        "inquiry_id": str(draft.inquiry_id),
        "quote_id": str(draft.quote_id),
        "subject": draft.subject,
        "body": draft.body,
        "language": draft.language,
        "status": draft.status,
        "approved_by": str(draft.approved_by) if draft.approved_by else None,
        "approved_at": iso_datetime(draft.approved_at) if draft.approved_at else None,
        "model_id": draft.model_id,
        "claims_used": draft.claims_json,
        "missing_information": draft.missing_information_json,
        "review_flags": draft.review_flags_json,
        "created_at": iso_datetime(draft.created_at),
        "updated_at": iso_datetime(draft.updated_at),
    }


@router.post("/inquiries/{inquiry_id}/email-drafts", status_code=status.HTTP_201_CREATED)
async def create_email_draft(
    inquiry_id: uuid.UUID,
    payload: EmailDraftCreate,
    context: EmailDraftContext,
    session: SessionDep,
    request: Request,
) -> dict[str, Any]:
    draft = await EmailDraftService(session).generate(
        tenant_id=context.tenant_id,
        inquiry_id=inquiry_id,
        quote_id=payload.quote_id,
        language=payload.language,
    )
    AuditService(session).record(
        tenant_id=context.tenant_id,
        actor_id=context.user_id,
        action="email.draft.create",
        resource_type="EMAIL_DRAFT",
        resource_id=draft.id,
        request_id=context.request_id,
        ip_hash=client_ip_hash(request),
        metadata={
            "inquiry_id": str(draft.inquiry_id),
            "quote_id": str(draft.quote_id),
            "language": draft.language,
            "model_id": draft.model_id,
        },
    )
    await commit_or_rollback(session)
    return envelope(_draft_detail(draft), context)


@router.get("/email-drafts/{draft_id}")
async def get_email_draft(
    draft_id: uuid.UUID,
    context: EmailReadContext,
    session: SessionDep,
) -> dict[str, Any]:
    draft = await EmailDraftService(session).get(
        tenant_id=context.tenant_id,
        draft_id=draft_id,
    )
    return envelope(_draft_detail(draft), context)


@router.patch("/email-drafts/{draft_id}")
async def update_email_draft(
    draft_id: uuid.UUID,
    payload: EmailDraftUpdate,
    context: EmailUpdateContext,
    session: SessionDep,
    request: Request,
) -> dict[str, Any]:
    draft = await EmailDraftService(session).update(
        tenant_id=context.tenant_id,
        draft_id=draft_id,
        subject=payload.subject,
        body=payload.body,
    )
    AuditService(session).record(
        tenant_id=context.tenant_id,
        actor_id=context.user_id,
        action="email.draft.update",
        resource_type="EMAIL_DRAFT",
        resource_id=draft.id,
        request_id=context.request_id,
        ip_hash=client_ip_hash(request),
        metadata={
            "fields": [
                name
                for name, value in (("subject", payload.subject), ("body", payload.body))
                if value is not None
            ]
        },
    )
    await commit_or_rollback(session)
    return envelope(_draft_detail(draft), context)


@router.post("/email-drafts/{draft_id}/approve")
async def approve_email_draft(
    draft_id: uuid.UUID,
    context: EmailApproveContext,
    session: SessionDep,
    request: Request,
) -> dict[str, Any]:
    draft = await EmailDraftService(session).approve(
        tenant_id=context.tenant_id,
        draft_id=draft_id,
        actor_id=context.user_id,
    )
    AuditService(session).record(
        tenant_id=context.tenant_id,
        actor_id=context.user_id,
        action="email.draft.approve",
        resource_type="EMAIL_DRAFT",
        resource_id=draft.id,
        request_id=context.request_id,
        ip_hash=client_ip_hash(request),
        metadata={
            "inquiry_id": str(draft.inquiry_id),
            "quote_id": str(draft.quote_id),
        },
    )
    await commit_or_rollback(session)
    return envelope(_draft_detail(draft), context)
