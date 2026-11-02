import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ContextDep, RequestContext, SessionDep
from app.db.tenant import set_tenant_context
from app.models.quote import Quote, QuoteEvent, QuoteItem
from app.pricing import PricingService, calculate_quote
from app.quotes import QuoteError, QuoteErrorCode, QuoteService, QuoteStatus

router = APIRouter(prefix="/quotes", tags=["quotes"])


class QuoteLineCreate(BaseModel):
    product_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    unit: str = Field(min_length=1, max_length=20)


class QuoteCreateRequest(BaseModel):
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    items: list[QuoteLineCreate] = Field(min_length=1)
    inquiry_id: uuid.UUID | None = None
    # inquiries are not modelled yet, so the caller may pass the customer explicitly.
    customer_id: uuid.UUID | None = None
    quote_no: str | None = Field(default=None, min_length=1, max_length=40)
    version_no: int = Field(default=1, ge=1)
    valid_until: date | None = None
    terms: dict[str, Any] = Field(default_factory=dict)
    source_snapshot: dict[str, Any] = Field(default_factory=dict)
    price_as_of: date | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class DecisionRequest(BaseModel):
    decision_note: str | None = Field(default=None, max_length=4000)


class CancelQuoteRequest(BaseModel):
    note: str | None = Field(default=None, max_length=4000)


def _iso_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _decimal_str(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _envelope(
    data: Any,
    context: RequestContext,
    *,
    page: int | None = None,
    page_size: int | None = None,
    total: int | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "request_id": context.request_id,
        "timestamp": _iso_datetime(datetime.now(UTC)),
    }
    if page is not None:
        meta.update({"page": page, "page_size": page_size, "total": total})
    return {"data": data, "meta": meta}


def _quote_summary(quote: Quote) -> dict[str, Any]:
    return {
        "id": str(quote.id),
        "inquiry_id": str(quote.inquiry_id) if quote.inquiry_id else None,
        "quote_no": quote.quote_no,
        "version_no": quote.version_no,
        "status": quote.status,
        "currency": quote.currency,
        "subtotal": _decimal_str(quote.subtotal),
        "subtotal_display": _decimal_str(quote.subtotal_display),
        "discount_total": _decimal_str(quote.discount_total),
        "freight_total": _decimal_str(quote.freight_total),
        "other_charges": _decimal_str(quote.other_charges),
        "grand_total": _decimal_str(quote.grand_total),
        "grand_total_display": _decimal_str(quote.grand_total_display),
        "valid_until": quote.valid_until.isoformat() if quote.valid_until else None,
        "created_by": str(quote.created_by) if quote.created_by else None,
        "created_at": _iso_datetime(quote.created_at),
        "updated_at": _iso_datetime(quote.updated_at),
    }


def _quote_item(item: QuoteItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "line_no": item.line_no,
        "product_id": str(item.product_id) if item.product_id else None,
        "product_snapshot": item.product_snapshot_json,
        "quantity": _decimal_str(item.quantity),
        "unit": item.unit,
        "priced_quantity": _decimal_str(item.priced_quantity),
        "price_unit": item.price_unit,
        "price_basis": item.price_basis,
        "unit_price": _decimal_str(item.unit_price),
        "unit_price_display": _decimal_str(item.unit_price_display),
        "line_total": _decimal_str(item.line_total),
        "line_total_display": _decimal_str(item.line_total_display),
        "price_source_ref": item.price_source_ref,
    }


def _quote_event(event: QuoteEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "event_type": event.event_type,
        "event_payload": event.event_payload,
        "actor_id": str(event.actor_id) if event.actor_id else None,
        "created_at": _iso_datetime(event.created_at),
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


async def _load_detail(
    session: AsyncSession,
    context: RequestContext,
    quote_id: uuid.UUID,
) -> dict[str, Any]:
    quote = await _get_quote(session, context.tenant_id, quote_id)
    items = list(
        await session.scalars(
            select(QuoteItem)
            .where(
                QuoteItem.tenant_id == context.tenant_id,
                QuoteItem.quote_id == quote.id,
            )
            .order_by(QuoteItem.line_no)
        )
    )
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


async def _commit(session: AsyncSession) -> None:
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise


def _generate_quote_no() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return f"Q-{stamp}-{uuid.uuid4().hex[:8].upper()}"


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_quote(
    payload: QuoteCreateRequest,
    context: ContextDep,
    session: SessionDep,
) -> dict[str, Any]:
    as_of = payload.price_as_of or datetime.now(UTC).date()
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
        )
        for item in payload.items
    ]
    calculation = calculate_quote(lines)

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
    await _commit(session)
    return _envelope(await _load_detail(session, context, quote.id), context)


@router.get("")
async def list_quotes(
    context: ContextDep,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[QuoteStatus | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    await set_tenant_context(session, context.tenant_id)
    conditions = [Quote.tenant_id == context.tenant_id]
    if status_filter is not None:
        conditions.append(Quote.status == status_filter.value)

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
    return _envelope(
        [_quote_summary(quote) for quote in quotes],
        context,
        page=page,
        page_size=page_size,
        total=int(total or 0),
    )


@router.get("/{quote_id}")
async def get_quote(
    quote_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
) -> dict[str, Any]:
    return _envelope(await _load_detail(session, context, quote_id), context)


@router.post("/{quote_id}/submit-approval")
async def submit_quote_for_approval(
    quote_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
) -> dict[str, Any]:
    await QuoteService(session).submit_for_approval(
        tenant_id=context.tenant_id,
        quote_id=quote_id,
        actor_id=context.user_id,
    )
    await _commit(session)
    return _envelope(await _load_detail(session, context, quote_id), context)


@router.post("/{quote_id}/approve")
async def approve_quote(
    quote_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    payload: DecisionRequest | None = None,
) -> dict[str, Any]:
    await QuoteService(session).approve(
        tenant_id=context.tenant_id,
        quote_id=quote_id,
        approver_id=context.user_id,
        note=payload.decision_note if payload else None,
    )
    await _commit(session)
    return _envelope(await _load_detail(session, context, quote_id), context)


@router.post("/{quote_id}/reject")
async def reject_quote(
    quote_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    payload: DecisionRequest | None = None,
) -> dict[str, Any]:
    await QuoteService(session).reject(
        tenant_id=context.tenant_id,
        quote_id=quote_id,
        approver_id=context.user_id,
        note=payload.decision_note if payload else None,
    )
    await _commit(session)
    return _envelope(await _load_detail(session, context, quote_id), context)


@router.post("/{quote_id}/cancel")
async def cancel_quote(
    quote_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
    payload: CancelQuoteRequest | None = None,
) -> dict[str, Any]:
    await QuoteService(session).cancel(
        tenant_id=context.tenant_id,
        quote_id=quote_id,
        actor_id=context.user_id,
        note=payload.note if payload else None,
    )
    await _commit(session)
    return _envelope(await _load_detail(session, context, quote_id), context)
