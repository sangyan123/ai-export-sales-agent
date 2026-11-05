import hashlib
import logging
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import envelope, iso_datetime
from app.api.deps import RequestContext, SessionDep, require_permission
from app.api.errors import ApiError
from app.core.config import settings
from app.core.permissions import Permission
from app.db.session import commit_or_rollback
from app.models.product import KnowledgeDocument
from app.storage import ObjectStorage, StorageError, get_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge-documents", tags=["knowledge-documents"])

ALLOWED_EXTENSIONS = frozenset({".pdf", ".docx", ".xlsx", ".xls", ".csv", ".txt"})
ALLOWED_CONTENT_TYPES = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "text/csv",
        "text/plain",
        "application/octet-stream",
    }
)
KNOWN_SOURCES = frozenset({"CATALOG", "PRICE_LIST", "CERTIFICATE", "SPEC_SHEET", "OTHER"})

KnowledgeReadContext = Annotated[
    RequestContext, Depends(require_permission(Permission.PRODUCT_READ))
]
KnowledgeWriteContext = Annotated[
    RequestContext, Depends(require_permission(Permission.PRODUCT_IMPORT))
]

StorageDep = Annotated[ObjectStorage, Depends(get_storage)]


def _safe_filename(name: str | None) -> str:
    raw = (name or "document").strip()
    raw = re.sub(r"[^\w.\- ()\u4e00-\u9fff]", "_", raw)
    raw = raw[:255]
    return raw or "document"


def _extension(filename: str) -> str:
    return ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""


def _object_key(tenant_id: uuid.UUID, doc_id: uuid.UUID, filename: str) -> str:
    safe = filename.replace("\\", "_").replace("/", "_")
    return f"knowledge/{tenant_id}/{doc_id}/{safe}"


def _document_detail(doc: KnowledgeDocument) -> dict[str, Any]:
    return {
        "id": str(doc.id),
        "object_key": doc.object_key,
        "filename": doc.filename,
        "content_type": doc.content_type,
        "size_bytes": doc.size_bytes,
        "checksum": doc.checksum,
        "source": doc.source,
        "description": doc.description,
        "parse_status": doc.parse_status,
        "uploaded_by": str(doc.uploaded_by) if doc.uploaded_by else None,
        "created_at": iso_datetime(doc.created_at),
        "updated_at": iso_datetime(doc.updated_at),
    }


async def _read_upload(file: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > settings.attachment_max_bytes:
            raise ApiError(
                413,
                "FILE_TOO_LARGE",
                f"file exceeds {settings.attachment_max_bytes // (1024 * 1024)} MB limit",
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _get_document(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
) -> KnowledgeDocument:
    doc = await session.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.tenant_id == tenant_id,
            KnowledgeDocument.id == document_id,
        )
    )
    if doc is None:
        raise ApiError(404, "KNOWLEDGE_DOCUMENT_NOT_FOUND", "knowledge document not found")
    return doc


@router.get("")
async def list_documents(
    context: KnowledgeReadContext,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    source: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    conditions = [KnowledgeDocument.tenant_id == context.tenant_id]
    if source:
        if source not in KNOWN_SOURCES:
            raise ApiError(422, "VALIDATION_ERROR", f"unknown source: {source}")
        conditions.append(KnowledgeDocument.source == source)
    if q:
        pattern = f"%{q.strip()}%"
        conditions.append(KnowledgeDocument.filename.ilike(pattern))

    total = await session.scalar(
        select(func.count()).select_from(KnowledgeDocument).where(*conditions)
    )
    documents = list(
        await session.scalars(
            select(KnowledgeDocument)
            .where(*conditions)
            .order_by(KnowledgeDocument.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return envelope(
        [_document_detail(doc) for doc in documents],
        context,
        page=page,
        page_size=page_size,
        total=int(total or 0),
    )


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: Annotated[UploadFile, File()],
    context: KnowledgeWriteContext,
    session: SessionDep,
    storage: StorageDep,
    source: Annotated[str, Form()] = "OTHER",
    description: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    if source not in KNOWN_SOURCES:
        raise ApiError(422, "VALIDATION_ERROR", f"source must be one of {sorted(KNOWN_SOURCES)}")

    data = await _read_upload(file)
    if not data:
        raise ApiError(422, "EMPTY_FILE", "uploaded file is empty")

    filename = _safe_filename(file.filename)
    ext = _extension(filename)
    if ext and ext not in ALLOWED_EXTENSIONS:
        raise ApiError(
            422,
            "UNSUPPORTED_FILE_TYPE",
            f"extension {ext!r} not allowed; supported: {sorted(ALLOWED_EXTENSIONS)}",
        )

    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_CONTENT_TYPES:
        content_type = "application/octet-stream"

    doc_id = uuid.uuid4()
    object_key = _object_key(context.tenant_id, doc_id, filename)

    try:
        await storage.put(object_key=object_key, data=data, content_type=content_type)
    except StorageError as exc:
        logger.warning("knowledge document upload failed: %s", exc)
        raise ApiError(502, "STORAGE_UNAVAILABLE", "document storage is unavailable") from exc

    doc = KnowledgeDocument(
        id=doc_id,
        tenant_id=context.tenant_id,
        object_key=object_key,
        filename=filename,
        content_type=content_type[:255],
        size_bytes=len(data),
        checksum=hashlib.sha256(data).hexdigest(),
        source=source,
        description=(description.strip()[:500] if description and description.strip() else None),
        parse_status="UPLOADED",
        uploaded_by=context.user_id,
    )
    session.add(doc)
    try:
        await session.flush()
        await session.refresh(doc)
        await commit_or_rollback(session)
    except Exception:
        try:
            await storage.delete(object_key=object_key)
        except StorageError:
            logger.warning("orphan object %s could not be cleaned up", object_key)
        raise
    return envelope(_document_detail(doc), context)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    context: KnowledgeWriteContext,
    session: SessionDep,
    storage: StorageDep,
) -> None:
    doc = await _get_document(session, context.tenant_id, document_id)
    object_key = doc.object_key
    await session.delete(doc)
    try:
        await commit_or_rollback(session)
    except Exception:
        raise
    try:
        await storage.delete(object_key=object_key)
    except StorageError as exc:
        logger.warning("failed to delete storage object %s: %s", object_key, exc)
