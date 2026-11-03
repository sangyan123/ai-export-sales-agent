import hashlib
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import envelope, iso_datetime
from app.api.deps import RequestContext, SessionDep, require_permission
from app.api.errors import ApiError
from app.audit import AuditService, client_ip_hash
from app.core.config import settings
from app.core.permissions import Permission
from app.db.session import commit_or_rollback
from app.db.tenant import set_tenant_context
from app.inquiries import (
    InquirySourceType,
    InquiryStatus,
    can_transition,
)
from app.models.customer import Customer
from app.models.inquiry import Inquiry, InquiryAttachment, InquiryRequirement
from app.models.tenant import TenantMembership
from app.storage import ObjectStorage, StorageError, get_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inquiries", tags=["inquiries"])

InquiryReadContext = Annotated[RequestContext, Depends(require_permission(Permission.INQUIRY_READ))]
InquiryCreateContext = Annotated[
    RequestContext, Depends(require_permission(Permission.INQUIRY_CREATE))
]
InquiryUpdateContext = Annotated[
    RequestContext, Depends(require_permission(Permission.INQUIRY_UPDATE))
]
StorageDep = Annotated[ObjectStorage, Depends(get_storage)]


def _record_inquiry_audit(
    request: Request,
    context: RequestContext,
    session: AsyncSession,
    action: str,
    inquiry_id: uuid.UUID,
    metadata: dict[str, Any] | None = None,
) -> None:
    AuditService(session).record(
        tenant_id=context.tenant_id,
        actor_id=context.user_id,
        action=action,
        resource_type="INQUIRY",
        resource_id=inquiry_id,
        request_id=context.request_id,
        ip_hash=client_ip_hash(request),
        metadata=metadata,
    )


class InquiryCreate(BaseModel):
    customer_id: uuid.UUID
    subject: str = Field(min_length=1, max_length=240)
    source_type: InquirySourceType = InquirySourceType.MANUAL
    source_ref: str | None = Field(default=None, max_length=255)
    raw_body: str | None = None
    language: str | None = Field(default=None, max_length=16)
    owner_user_id: uuid.UUID | None = None
    received_at: datetime | None = None

    @field_validator("subject")
    @classmethod
    def strip_subject(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class InquiryUpdate(BaseModel):
    customer_id: uuid.UUID | None = None
    subject: str | None = Field(default=None, min_length=1, max_length=240)
    source_type: InquirySourceType | None = None
    source_ref: str | None = Field(default=None, max_length=255)
    raw_body: str | None = None
    language: str | None = Field(default=None, max_length=16)
    owner_user_id: uuid.UUID | None = None
    status: InquiryStatus | None = None

    @field_validator("subject")
    @classmethod
    def strip_subject(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class RequirementUpdate(BaseModel):
    schema_version: int = Field(default=1, ge=1)
    confirmed: dict[str, Any] = Field(default_factory=dict)


def _inquiry_summary(inquiry: Inquiry) -> dict[str, Any]:
    return {
        "id": str(inquiry.id),
        "customer_id": str(inquiry.customer_id),
        "subject": inquiry.subject,
        "source_type": inquiry.source_type,
        "status": inquiry.status,
        "owner_user_id": str(inquiry.owner_user_id) if inquiry.owner_user_id else None,
        "received_at": iso_datetime(inquiry.received_at),
        "created_at": iso_datetime(inquiry.created_at),
        "updated_at": iso_datetime(inquiry.updated_at),
    }


def _inquiry_detail(
    inquiry: Inquiry, attachments: list[InquiryAttachment] | None = None
) -> dict[str, Any]:
    return {
        **_inquiry_summary(inquiry),
        "source_ref": inquiry.source_ref,
        "raw_body": inquiry.raw_body,
        "language": inquiry.language,
        "attachments": [_attachment_detail(item) for item in attachments or []],
    }


def _attachment_detail(attachment: InquiryAttachment) -> dict[str, Any]:
    return {
        "id": str(attachment.id),
        "inquiry_id": str(attachment.inquiry_id),
        "filename": attachment.filename,
        "content_type": attachment.content_type,
        "size_bytes": attachment.size_bytes,
        "checksum": attachment.checksum,
        "scan_status": attachment.scan_status,
        "created_at": iso_datetime(attachment.created_at),
    }


def _requirement_detail(requirement: InquiryRequirement) -> dict[str, Any]:
    return {
        "id": str(requirement.id),
        "inquiry_id": str(requirement.inquiry_id),
        "schema_version": requirement.schema_version,
        "parsed": requirement.parsed_json,
        "confirmed": requirement.confirmed_json,
        "confidence": requirement.confidence_json,
        "evidence": requirement.evidence_json,
        "model_id": requirement.model_id,
        "created_at": iso_datetime(requirement.created_at),
        "updated_at": iso_datetime(requirement.updated_at),
    }


async def _get_inquiry(
    session: AsyncSession, tenant_id: uuid.UUID, inquiry_id: uuid.UUID
) -> Inquiry:
    await set_tenant_context(session, tenant_id)
    inquiry = await session.scalar(
        select(Inquiry).where(Inquiry.tenant_id == tenant_id, Inquiry.id == inquiry_id)
    )
    if inquiry is None:
        raise ApiError(404, "INQUIRY_NOT_FOUND", "inquiry not found")
    return inquiry


async def _load_attachments(
    session: AsyncSession, tenant_id: uuid.UUID, inquiry_id: uuid.UUID
) -> list[InquiryAttachment]:
    return list(
        await session.scalars(
            select(InquiryAttachment)
            .where(
                InquiryAttachment.tenant_id == tenant_id,
                InquiryAttachment.inquiry_id == inquiry_id,
            )
            .order_by(InquiryAttachment.created_at, InquiryAttachment.id)
        )
    )


async def _read_upload(file: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > settings.attachment_max_bytes:
            raise ApiError(
                413,
                "ATTACHMENT_TOO_LARGE",
                f"attachment exceeds {settings.attachment_max_bytes} bytes",
            )
        chunks.append(chunk)
    if total == 0:
        raise ApiError(400, "ATTACHMENT_EMPTY", "attachment file is empty")
    return b"".join(chunks)


def _normalize_filename(raw: str | None) -> str:
    filename = (raw or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not filename or filename in {".", ".."}:
        raise ApiError(400, "ATTACHMENT_FILENAME_INVALID", "attachment filename is required")
    if len(filename) > 255:
        raise ApiError(
            400,
            "ATTACHMENT_FILENAME_INVALID",
            "attachment filename must be at most 255 characters",
        )
    return filename


def _attachment_object_key(tenant_id: uuid.UUID, inquiry_id: uuid.UUID, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
        suffix = ""
    return f"tenants/{tenant_id}/inquiries/{inquiry_id}/{uuid.uuid4().hex}{suffix}"


async def _ensure_customer(
    session: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID
) -> None:
    exists = await session.scalar(
        select(Customer.id).where(Customer.tenant_id == tenant_id, Customer.id == customer_id)
    )
    if exists is None:
        raise ApiError(404, "CUSTOMER_NOT_FOUND", "customer not found")


async def _ensure_owner_member(
    session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID | None
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
        raise ApiError(400, "OWNER_NOT_MEMBER", "owner is not an active tenant member")


def _ensure_status_transition(inquiry: Inquiry, target: InquiryStatus) -> None:
    if target.value == inquiry.status:
        return
    if not can_transition(inquiry.status, target):
        raise ApiError(
            409,
            "INVALID_STATUS_TRANSITION",
            f"inquiry status {inquiry.status} cannot move to {target.value}",
        )


@router.get("")
async def list_inquiries(
    context: InquiryReadContext,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[InquiryStatus | None, Query(alias="status")] = None,
    customer_id: uuid.UUID | None = None,
    owner_user_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
) -> dict[str, Any]:
    await set_tenant_context(session, context.tenant_id)
    conditions = [Inquiry.tenant_id == context.tenant_id]
    if status_filter is not None:
        conditions.append(Inquiry.status == status_filter.value)
    if customer_id is not None:
        conditions.append(Inquiry.customer_id == customer_id)
    if owner_user_id is not None:
        conditions.append(Inquiry.owner_user_id == owner_user_id)
    if q:
        pattern = f"%{q.strip()}%"
        conditions.append(or_(Inquiry.subject.ilike(pattern), Inquiry.raw_body.ilike(pattern)))

    total = await session.scalar(select(func.count()).select_from(Inquiry).where(*conditions))
    inquiries = list(
        await session.scalars(
            select(Inquiry)
            .where(*conditions)
            .order_by(Inquiry.received_at.desc(), Inquiry.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return envelope(
        [_inquiry_summary(inquiry) for inquiry in inquiries],
        context,
        page=page,
        page_size=page_size,
        total=int(total or 0),
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_inquiry(
    payload: InquiryCreate,
    context: InquiryCreateContext,
    session: SessionDep,
    request: Request,
) -> dict[str, Any]:
    await set_tenant_context(session, context.tenant_id)
    await _ensure_customer(session, context.tenant_id, payload.customer_id)
    owner_user_id = payload.owner_user_id or context.user_id
    await _ensure_owner_member(session, context.tenant_id, owner_user_id)

    inquiry = Inquiry(
        tenant_id=context.tenant_id,
        customer_id=payload.customer_id,
        subject=payload.subject,
        source_type=payload.source_type.value,
        source_ref=payload.source_ref,
        raw_body=payload.raw_body,
        language=payload.language,
        status=InquiryStatus.RECEIVED.value,
        owner_user_id=owner_user_id,
    )
    if payload.received_at is not None:
        inquiry.received_at = payload.received_at
    session.add(inquiry)
    await session.flush()
    await session.refresh(inquiry)
    _record_inquiry_audit(
        request,
        context,
        session,
        "inquiry.create",
        inquiry.id,
        {
            "subject": inquiry.subject,
            "customer_id": str(inquiry.customer_id),
            "source_type": inquiry.source_type,
        },
    )
    await commit_or_rollback(session)
    return envelope(_inquiry_detail(inquiry), context)


@router.get("/{inquiry_id}")
async def get_inquiry(
    inquiry_id: uuid.UUID,
    context: InquiryReadContext,
    session: SessionDep,
) -> dict[str, Any]:
    inquiry = await _get_inquiry(session, context.tenant_id, inquiry_id)
    attachments = await _load_attachments(session, context.tenant_id, inquiry.id)
    return envelope(_inquiry_detail(inquiry, attachments), context)


@router.patch("/{inquiry_id}")
async def update_inquiry(
    inquiry_id: uuid.UUID,
    payload: InquiryUpdate,
    context: InquiryUpdateContext,
    session: SessionDep,
    request: Request,
) -> dict[str, Any]:
    inquiry = await _get_inquiry(session, context.tenant_id, inquiry_id)
    data = payload.model_dump(exclude_unset=True)

    for field in ("customer_id", "subject", "source_type", "status"):
        if field in data and data[field] is None:
            raise ApiError(422, "VALIDATION_ERROR", f"{field} cannot be null")

    if "customer_id" in data:
        await _ensure_customer(session, context.tenant_id, data["customer_id"])
    if "owner_user_id" in data:
        await _ensure_owner_member(session, context.tenant_id, data["owner_user_id"])
    if "source_type" in data:
        data["source_type"] = payload.source_type.value
    if "status" in data:
        _ensure_status_transition(inquiry, payload.status)
        data["status"] = payload.status.value

    for field, value in data.items():
        setattr(inquiry, field, value)
    await session.flush()
    await session.refresh(inquiry)
    _record_inquiry_audit(
        request,
        context,
        session,
        "inquiry.update",
        inquiry.id,
        {"fields": sorted(data)},
    )
    await commit_or_rollback(session)
    attachments = await _load_attachments(session, context.tenant_id, inquiry.id)
    return envelope(_inquiry_detail(inquiry, attachments), context)


@router.post("/{inquiry_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    inquiry_id: uuid.UUID,
    file: Annotated[UploadFile, File()],
    context: InquiryUpdateContext,
    session: SessionDep,
    storage: StorageDep,
    request: Request,
) -> dict[str, Any]:
    inquiry = await _get_inquiry(session, context.tenant_id, inquiry_id)
    data = await _read_upload(file)
    filename = _normalize_filename(file.filename)
    content_type = file.content_type or "application/octet-stream"
    object_key = _attachment_object_key(context.tenant_id, inquiry.id, filename)

    try:
        await storage.put(object_key=object_key, data=data, content_type=content_type)
    except StorageError as exc:
        logger.warning("attachment upload failed for inquiry %s: %s", inquiry.id, exc)
        raise ApiError(502, "STORAGE_UNAVAILABLE", "attachment storage is unavailable") from exc

    attachment = InquiryAttachment(
        tenant_id=context.tenant_id,
        inquiry_id=inquiry.id,
        object_key=object_key,
        filename=filename,
        content_type=content_type[:255],
        size_bytes=len(data),
        checksum=hashlib.sha256(data).hexdigest(),
        scan_status="PENDING",
    )
    session.add(attachment)
    try:
        await session.flush()
        await session.refresh(attachment)
        _record_inquiry_audit(
            request,
            context,
            session,
            "inquiry.attachment.upload",
            inquiry.id,
            {
                "attachment_id": str(attachment.id),
                "filename": attachment.filename,
                "size_bytes": attachment.size_bytes,
            },
        )
        await commit_or_rollback(session)
    except Exception:
        try:
            await storage.delete(object_key=object_key)
        except StorageError as exc:
            logger.warning("failed to clean up orphaned object %s: %s", object_key, exc)
        raise
    return envelope(_attachment_detail(attachment), context)


@router.get("/{inquiry_id}/requirements")
async def get_requirements(
    inquiry_id: uuid.UUID,
    context: InquiryReadContext,
    session: SessionDep,
) -> dict[str, Any]:
    await _get_inquiry(session, context.tenant_id, inquiry_id)
    requirement = await session.scalar(
        select(InquiryRequirement)
        .where(
            InquiryRequirement.tenant_id == context.tenant_id,
            InquiryRequirement.inquiry_id == inquiry_id,
        )
        .order_by(InquiryRequirement.schema_version.desc())
        .limit(1)
    )
    return envelope(_requirement_detail(requirement) if requirement else None, context)


@router.patch("/{inquiry_id}/requirements")
async def update_requirements(
    inquiry_id: uuid.UUID,
    payload: RequirementUpdate,
    context: InquiryUpdateContext,
    session: SessionDep,
) -> dict[str, Any]:
    await _get_inquiry(session, context.tenant_id, inquiry_id)
    requirement = await session.scalar(
        select(InquiryRequirement).where(
            InquiryRequirement.tenant_id == context.tenant_id,
            InquiryRequirement.inquiry_id == inquiry_id,
            InquiryRequirement.schema_version == payload.schema_version,
        )
    )
    if requirement is None:
        requirement = InquiryRequirement(
            tenant_id=context.tenant_id,
            inquiry_id=inquiry_id,
            schema_version=payload.schema_version,
        )
        session.add(requirement)
    requirement.confirmed_json = payload.confirmed
    await session.flush()
    await session.refresh(requirement)
    await commit_or_rollback(session)
    return envelope(_requirement_detail(requirement), context)
