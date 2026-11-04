import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from io import BytesIO
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import decimal_str, envelope, iso_datetime
from app.api.deps import RequestContext, SessionDep, require_permission
from app.audit import AuditService, client_ip_hash
from app.core.permissions import Permission
from app.db.session import commit_or_rollback
from app.db.tenant import set_tenant_context
from app.models.customer import Customer
from app.models.inquiry import Inquiry
from app.models.quote import Quote, QuoteEvent, QuoteItem
from app.pricing import PricingPolicyService, PricingService, calculate_quote, enforce_moq_policy
from app.quotes import QuoteError, QuoteErrorCode, QuoteService, QuoteStatus
from app.quotes.documents import render_quote_pdf, render_quote_xlsx

router = APIRouter(prefix="/quotes", tags=["quotes"])

QuoteCreateContext = Annotated[RequestContext, Depends(require_permission(Permission.QUOTE_CREATE))]
QuoteReadContext = Annotated[RequestContext, Depends(require_permission(Permission.QUOTE_READ))]
QuoteSubmitContext = Annotated[RequestContext, Depends(require_permission(Permission.QUOTE_SUBMIT))]
QuoteApproveContext = Annotated[
    RequestContext, Depends(require_permission(Permission.QUOTE_APPROVE))
]
QuoteCancelContext = Annotated[RequestContext, Depends(require_permission(Permission.QUOTE_CANCEL))]
QuoteCalculateContext = Annotated[
    RequestContext, Depends(require_permission(Permission.QUOTE_CALCULATE))
]
QuoteSendContext = Annotated[RequestContext, Depends(require_permission(Permission.QUOTE_SUBMIT))]
QuoteExpireContext = Annotated[RequestContext, Depends(require_permission(Permission.QUOTE_CANCEL))]


class QuoteLineCreate(BaseModel):
    product_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    unit: str = Field(min_length=1, max_length=20)


class QuoteCreateRequest(BaseModel):
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    items: list[QuoteLineCreate] = Field(min_length=1)
    inquiry_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    quote_no: str | None = Field(default=None, min_length=1, max_length=40)
    version_no: int = Field(default=1, ge=1)
    valid_until: date | None = None
    terms: dict[str, Any] = Field(default_factory=dict)
    source_snapshot: dict[str, Any] = Field(default_factory=dict)
    price_as_of: date | None = None
    discount_total: Decimal = Field(default=Decimal("0"), ge=0)
    freight_total: Decimal = Field(default=Decimal("0"), ge=0)
    other_charges: Decimal = Field(default=Decimal("0"), ge=0)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class DecisionRequest(BaseModel):
    decision_note: str | None = Field(default=None, max_length=4000)


class CancelQuoteRequest(BaseModel):
    note: str | None = Field(default=None, max_length=4000)


class RecalculateQuoteRequest(BaseModel):
    price_as_of: date | None = None


class SendQuoteRequest(BaseModel):
    note: str | None = Field(default=None, max_length=4000)


class ExpireQuoteRequest(BaseModel):
    as_of: date | None = None


class CreateVersionRequest(BaseModel):
    valid_until: date | None = None


class QuoteDocumentFormat(StrEnum):
    PDF = "PDF"
    XLSX = "XLSX"


def _quote_summary(quote: Quote) -> dict[str, Any]:
    return {
        "id": str(quote.id),
        "inquiry_id": str(quote.inquiry_id) if quote.inquiry_id else None,
        "quote_no": quote.quote_no,
        "version_no": quote.version_no,
        "status": quote.status,
        "currency": quote.currency,
        "subtotal": decimal_str(quote.subtotal),
        "subtotal_display": decimal_str(quote.subtotal_display),
        "discount_total": decimal_str(quote.discount_total),
        "freight_total": decimal_str(quote.freight_total),
        "other_charges": decimal_str(quote.other_charges),
        "grand_total": decimal_str(quote.grand_total),
        "grand_total_display": decimal_str(quote.grand_total_display),
        "valid_until": quote.valid_until.isoformat() if quote.valid_until else None,
        "created_by": str(quote.created_by) if quote.created_by else None,
        "created_at": iso_datetime(quote.created_at),
        "updated_at": iso_datetime(quote.updated_at),
    }


def _quote_item(item: QuoteItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "line_no": item.line_no,
        "product_id": str(item.product_id) if item.product_id else None,
        "product_snapshot": item.product_snapshot_json,
        "quantity": decimal_str(item.quantity),
        "unit": item.unit,
        "priced_quantity": decimal_str(item.priced_quantity),
        "price_unit": item.price_unit,
        "price_basis": item.price_basis,
        "unit_price": decimal_str(item.unit_price),
        "unit_price_display": decimal_str(item.unit_price_display),
        "line_total": decimal_str(item.line_total),
        "line_total_display": decimal_str(item.line_total_display),
        "price_source_ref": item.price_source_ref,
    }


def _quote_event(event: QuoteEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "event_type": event.event_type,
        "event_payload": event.event_payload,
        "actor_id": str(event.actor_id) if event.actor_id else None,
        "created_at": iso_datetime(event.created_at),
    }


def _quote_detail(
    quote: Quote,
    items: list[QuoteItem],
    events: list[QuoteEvent],
) -> dict[str, Any]:
    return {
        **_quote_summary(quote),
        "terms": quote.terms_json,
        "source_snapshot": quote.source_snapshot_json,
        "items": [_quote_item(item) for item in items],
        "events": [_quote_event(event) for event in events],
    }


async def _get_quote(session: AsyncSession, tenant_id: uuid.UUID, quote_id: uuid.UUID) -> Quote:
    await set_tenant_context(session, tenant_id)
    quote = await session.scalar(
        select(Quote).where(Quote.tenant_id == tenant_id, Quote.id == quote_id)
    )
    if quote is None:
        raise QuoteError(QuoteErrorCode.QUOTE_NOT_FOUND, "quote not found")
    return quote


async def _load_items(
    session: AsyncSession, tenant_id: uuid.UUID, quote_id: uuid.UUID
) -> list[QuoteItem]:
    return list(
        await session.scalars(
            select(QuoteItem)
            .where(
                QuoteItem.tenant_id == tenant_id,
                QuoteItem.quote_id == quote_id,
            )
            .order_by(QuoteItem.line_no)
        )
    )


async def _load_customer_name(
    session: AsyncSession, tenant_id: uuid.UUID, inquiry_id: uuid.UUID | None
) -> str | None:
    if inquiry_id is None:
        return None
    return await session.scalar(
        select(Customer.company_name)
        .join(
            Inquiry,
            (Inquiry.tenant_id == Customer.tenant_id) & (Inquiry.customer_id == Customer.id),
        )
        .where(Inquiry.tenant_id == tenant_id, Inquiry.id == inquiry_id)
    )


def _document_filename(quote: Quote, extension: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", quote.quote_no).strip("._") or "quote"
    return f"{stem}-v{quote.version_no}.{extension}"


async def _load_detail(
    session: AsyncSession,
    context: RequestContext,
    quote_id: uuid.UUID,
) -> dict[str, Any]:
    quote = await _get_quote(session, context.tenant_id, quote_id)
    items = await _load_items(session, context.tenant_id, quote.id)
    events = list(
        await session.scalars(
            select(QuoteEvent)
            .where(
                QuoteEvent.tenant_id == context.tenant_id,
                QuoteEvent.quote_id == quote.id,
            )
            .order_by(QuoteEvent.created_at, QuoteEvent.id)
        )
    )
    return _quote_detail(quote, items, events)


def _generate_quote_no() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return f"Q-{stamp}-{uuid.uuid4().hex[:8].upper()}"


def _record_audit(
    request: Request,
    context: RequestContext,
    session: AsyncSession,
    action: str,
    resource_id: uuid.UUID,
    metadata: dict[str, Any] | None = None,
) -> None:
    AuditService(session).record(
        tenant_id=context.tenant_id,
        actor_id=context.user_id,
        action=action,
        resource_type="QUOTE",
        resource_id=resource_id,
        request_id=context.request_id,
        ip_hash=client_ip_hash(request),
        metadata=metadata,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_quote(
    payload: QuoteCreateRequest,
    context: QuoteCreateContext,
    session: SessionDep,
    request: Request,
) -> dict[str, Any]:
    as_of = payload.price_as_of or datetime.now(UTC).date()
    policy = await PricingPolicyService(session).effective(context.tenant_id)
    pricing = PricingService.with_default_sources(session)
    lines = [
        await pricing.calculate_line(
            tenant_id=context.tenant_id,
            product_id=item.product_id,
            quantity=item.quantity,
            unit=item.unit,
            currency=payload.currency,
            as_of=as_of,
            customer_id=payload.customer_id,
            policy=policy.rounding,
        )
        for item in payload.items
    ]
    enforce_moq_policy(lines, policy)
    calculation = calculate_quote(
        lines,
        discount_total=payload.discount_total,
        freight_total=payload.freight_total,
        other_charges=payload.other_charges,
        policy=policy.rounding,
    )

    quote = await QuoteService(session).create_draft(
        tenant_id=context.tenant_id,
        actor_id=context.user_id,
        quote_no=payload.quote_no or _generate_quote_no(),
        calculation=calculation,
        inquiry_id=payload.inquiry_id,
        valid_until=payload.valid_until,
        terms=payload.terms,
        source_snapshot=payload.source_snapshot,
        version_no=payload.version_no,
    )
    _record_audit(
        request,
        context,
        session,
        "quote.create",
        quote.id,
        {
            "quote_no": quote.quote_no,
            "version_no": quote.version_no,
            "grand_total": decimal_str(quote.grand_total),
            "inquiry_id": str(quote.inquiry_id) if quote.inquiry_id else None,
        },
    )
    await commit_or_rollback(session)
    return envelope(await _load_detail(session, context, quote.id), context)


@router.get("")
async def list_quotes(
    context: QuoteReadContext,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[QuoteStatus | None, Query(alias="status")] = None,
    quote_no: Annotated[str | None, Query(max_length=40)] = None,
) -> dict[str, Any]:
    await set_tenant_context(session, context.tenant_id)
    conditions = [Quote.tenant_id == context.tenant_id]
    if status_filter is not None:
        conditions.append(Quote.status == status_filter.value)
    if quote_no is not None:
        conditions.append(Quote.quote_no == quote_no)

    total = await session.scalar(select(func.count()).select_from(Quote).where(*conditions))
    quotes = list(
        await session.scalars(
            select(Quote)
            .where(*conditions)
            .order_by(Quote.created_at.desc(), Quote.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return envelope(
        [_quote_summary(quote) for quote in quotes],
        context,
        page=page,
        page_size=page_size,
        total=int(total or 0),
    )


@router.get("/{quote_id}")
async def get_quote(
    quote_id: uuid.UUID,
    context: QuoteReadContext,
    session: SessionDep,
) -> dict[str, Any]:
    return envelope(await _load_detail(session, context, quote_id), context)


@router.post("/{quote_id}/submit-approval")
async def submit_quote_for_approval(
    quote_id: uuid.UUID,
    context: QuoteSubmitContext,
    session: SessionDep,
    request: Request,
) -> dict[str, Any]:
    task = await QuoteService(session).submit_for_approval(
        tenant_id=context.tenant_id,
        quote_id=quote_id,
        actor_id=context.user_id,
    )
    _record_audit(
        request,
        context,
        session,
        "quote.submit",
        quote_id,
        {"approval_task_id": str(task.id)},
    )
    await commit_or_rollback(session)
    return envelope(await _load_detail(session, context, quote_id), context)


@router.post("/{quote_id}/approve")
async def approve_quote(
    quote_id: uuid.UUID,
    context: QuoteApproveContext,
    session: SessionDep,
    request: Request,
    payload: DecisionRequest | None = None,
) -> dict[str, Any]:
    note = payload.decision_note if payload else None
    await QuoteService(session).approve(
        tenant_id=context.tenant_id,
        quote_id=quote_id,
        approver_id=context.user_id,
        note=note,
    )
    _record_audit(request, context, session, "quote.approve", quote_id, {"note": note})
    await commit_or_rollback(session)
    return envelope(await _load_detail(session, context, quote_id), context)


@router.post("/{quote_id}/reject")
async def reject_quote(
    quote_id: uuid.UUID,
    context: QuoteApproveContext,
    session: SessionDep,
    request: Request,
    payload: DecisionRequest | None = None,
) -> dict[str, Any]:
    note = payload.decision_note if payload else None
    await QuoteService(session).reject(
        tenant_id=context.tenant_id,
        quote_id=quote_id,
        approver_id=context.user_id,
        note=note,
    )
    _record_audit(request, context, session, "quote.reject", quote_id, {"note": note})
    await commit_or_rollback(session)
    return envelope(await _load_detail(session, context, quote_id), context)


@router.post("/{quote_id}/cancel")
async def cancel_quote(
    quote_id: uuid.UUID,
    context: QuoteCancelContext,
    session: SessionDep,
    request: Request,
    payload: CancelQuoteRequest | None = None,
) -> dict[str, Any]:
    note = payload.note if payload else None
    await QuoteService(session).cancel(
        tenant_id=context.tenant_id,
        quote_id=quote_id,
        actor_id=context.user_id,
        note=note,
    )
    _record_audit(request, context, session, "quote.cancel", quote_id, {"note": note})
    await commit_or_rollback(session)
    return envelope(await _load_detail(session, context, quote_id), context)


@router.post("/{quote_id}/recalculate")
async def recalculate_quote(
    quote_id: uuid.UUID,
    context: QuoteCalculateContext,
    session: SessionDep,
    request: Request,
    payload: RecalculateQuoteRequest | None = None,
) -> dict[str, Any]:
    as_of = (payload.price_as_of if payload else None) or datetime.now(UTC).date()
    quote = await QuoteService(session).recalculate(
        tenant_id=context.tenant_id,
        quote_id=quote_id,
        actor_id=context.user_id,
        as_of=as_of,
    )
    _record_audit(
        request,
        context,
        session,
        "quote.recalculate",
        quote_id,
        {"price_as_of": as_of.isoformat(), "grand_total": decimal_str(quote.grand_total)},
    )
    await commit_or_rollback(session)
    return envelope(await _load_detail(session, context, quote_id), context)


@router.post("/{quote_id}/revise")
async def revise_quote(
    quote_id: uuid.UUID,
    context: QuoteCreateContext,
    session: SessionDep,
    request: Request,
) -> dict[str, Any]:
    await QuoteService(session).revise(
        tenant_id=context.tenant_id,
        quote_id=quote_id,
        actor_id=context.user_id,
    )
    _record_audit(request, context, session, "quote.revise", quote_id)
    await commit_or_rollback(session)
    return envelope(await _load_detail(session, context, quote_id), context)


@router.post("/{quote_id}/send")
async def send_quote(
    quote_id: uuid.UUID,
    context: QuoteSendContext,
    session: SessionDep,
    request: Request,
    payload: SendQuoteRequest | None = None,
) -> dict[str, Any]:
    note = payload.note if payload else None
    await QuoteService(session).mark_sent(
        tenant_id=context.tenant_id,
        quote_id=quote_id,
        actor_id=context.user_id,
        note=note,
    )
    _record_audit(request, context, session, "quote.send", quote_id, {"note": note})
    await commit_or_rollback(session)
    return envelope(await _load_detail(session, context, quote_id), context)


@router.post("/{quote_id}/expire")
async def expire_quote(
    quote_id: uuid.UUID,
    context: QuoteExpireContext,
    session: SessionDep,
    request: Request,
    payload: ExpireQuoteRequest | None = None,
) -> dict[str, Any]:
    as_of = (payload.as_of if payload else None) or datetime.now(UTC).date()
    await QuoteService(session).expire(
        tenant_id=context.tenant_id,
        quote_id=quote_id,
        as_of=as_of,
        actor_id=context.user_id,
    )
    _record_audit(request, context, session, "quote.expire", quote_id, {"as_of": as_of.isoformat()})
    await commit_or_rollback(session)
    return envelope(await _load_detail(session, context, quote_id), context)


@router.post("/{quote_id}/versions", status_code=status.HTTP_201_CREATED)
async def create_quote_version(
    quote_id: uuid.UUID,
    context: QuoteCreateContext,
    session: SessionDep,
    request: Request,
    payload: CreateVersionRequest | None = None,
) -> dict[str, Any]:
    version = await QuoteService(session).create_version(
        tenant_id=context.tenant_id,
        quote_id=quote_id,
        actor_id=context.user_id,
        valid_until=payload.valid_until if payload else None,
    )
    _record_audit(
        request,
        context,
        session,
        "quote.create_version",
        quote_id,
        {
            "new_quote_id": str(version.id),
            "quote_no": version.quote_no,
            "source_version_no": version.version_no - 1,
            "new_version_no": version.version_no,
        },
    )
    await commit_or_rollback(session)
    return envelope(await _load_detail(session, context, version.id), context)


@router.post("/{quote_id}/documents")
async def generate_quote_document(
    quote_id: uuid.UUID,
    context: QuoteReadContext,
    session: SessionDep,
    format: Annotated[QuoteDocumentFormat, Query()] = QuoteDocumentFormat.PDF,
) -> StreamingResponse:
    quote = await _get_quote(session, context.tenant_id, quote_id)
    items = await _load_items(session, context.tenant_id, quote.id)
    customer_name = await _load_customer_name(session, context.tenant_id, quote.inquiry_id)

    if format is QuoteDocumentFormat.PDF:
        payload = render_quote_pdf(quote=quote, items=items, customer_name=customer_name)
        media_type = "application/pdf"
        extension = "pdf"
    else:
        payload = render_quote_xlsx(quote=quote, items=items, customer_name=customer_name)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        extension = "xlsx"

    filename = _document_filename(quote, extension)
    return StreamingResponse(
        BytesIO(payload),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
