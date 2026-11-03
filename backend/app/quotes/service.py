import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tenant import set_tenant_context
from app.inquiries import InquiryStatus, can_transition
from app.models.inquiry import Inquiry
from app.models.product import Product
from app.models.quote import ApprovalTask, Quote, QuoteEvent, QuoteItem
from app.pricing.engine import LineCalculation, PriceSource, QuoteCalculation


class QuoteErrorCode(StrEnum):
    QUOTE_NOT_FOUND = "QUOTE_NOT_FOUND"
    QUOTE_VERSION_EXISTS = "QUOTE_VERSION_EXISTS"
    QUOTE_EMPTY = "QUOTE_EMPTY"
    INVALID_QUOTE_NO = "INVALID_QUOTE_NO"
    PRODUCT_NOT_FOUND = "PRODUCT_NOT_FOUND"
    INQUIRY_NOT_FOUND = "INQUIRY_NOT_FOUND"
    INVALID_STATUS_TRANSITION = "INVALID_STATUS_TRANSITION"
    APPROVAL_NOT_FOUND = "APPROVAL_NOT_FOUND"
    APPROVAL_AMBIGUOUS = "APPROVAL_AMBIGUOUS"
    SELF_APPROVAL_FORBIDDEN = "SELF_APPROVAL_FORBIDDEN"
    VALIDITY_NOT_REACHED = "VALIDITY_NOT_REACHED"


class QuoteError(Exception):
    def __init__(self, code: QuoteErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class QuoteStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SENT = "SENT"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class QuoteEventType(StrEnum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVISED = "REVISED"
    CANCELLED = "CANCELLED"
    SENT = "SENT"
    EXPIRED = "EXPIRED"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


APPROVAL_OBJECT_TYPE = "QUOTE"
QUOTE_APPROVAL_TYPE = "QUOTE_APPROVAL"


class QuoteService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_draft(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_id: uuid.UUID,
        quote_no: str,
        calculation: QuoteCalculation,
        inquiry_id: uuid.UUID | None = None,
        valid_until: date | None = None,
        terms: Mapping[str, Any] | None = None,
        source_snapshot: Mapping[str, Any] | None = None,
        version_no: int = 1,
    ) -> Quote:
        await set_tenant_context(self._session, tenant_id)
        quote_no = quote_no.strip()
        if not quote_no or len(quote_no) > 40:
            raise QuoteError(
                QuoteErrorCode.INVALID_QUOTE_NO,
                "quote number must be between 1 and 40 characters",
            )
        if version_no < 1:
            raise QuoteError(QuoteErrorCode.INVALID_QUOTE_NO, "version number must be at least 1")
        if not calculation.lines:
            raise QuoteError(QuoteErrorCode.QUOTE_EMPTY, "quote must contain at least one line")

        existing = await self._session.scalar(
            select(Quote.id).where(
                Quote.tenant_id == tenant_id,
                Quote.quote_no == quote_no,
                Quote.version_no == version_no,
            )
        )
        if existing is not None:
            raise QuoteError(
                QuoteErrorCode.QUOTE_VERSION_EXISTS,
                f"quote {quote_no} version {version_no} already exists",
            )

        products = await self._load_products(
            tenant_id=tenant_id,
            product_ids={line.product_id for line in calculation.lines},
        )
        inquiry = (
            await self._load_inquiry(tenant_id, inquiry_id) if inquiry_id is not None else None
        )

        quote = Quote(
            tenant_id=tenant_id,
            inquiry_id=inquiry_id,
            quote_no=quote_no,
            version_no=version_no,
            status=QuoteStatus.DRAFT.value,
            currency=calculation.currency.upper(),
            subtotal=calculation.subtotal,
            subtotal_display=calculation.subtotal_display,
            discount_total=calculation.discount_total,
            discount_total_display=calculation.discount_total_display,
            freight_total=calculation.freight_total,
            freight_total_display=calculation.freight_total_display,
            other_charges=calculation.other_charges,
            other_charges_display=calculation.other_charges_display,
            grand_total=calculation.grand_total,
            grand_total_display=calculation.grand_total_display,
            valid_until=valid_until,
            terms_json=dict(terms or {}),
            source_snapshot_json=dict(source_snapshot or {}),
            created_by=actor_id,
        )
        self._session.add(quote)
        await self._session.flush()

        self._session.add_all(
            [
                self._build_item(
                    quote=quote,
                    line_no=line_no,
                    line=line,
                    product=products[line.product_id],
                )
                for line_no, line in enumerate(calculation.lines, start=1)
            ]
        )
        self._add_event(
            tenant_id=tenant_id,
            quote_id=quote.id,
            event_type=QuoteEventType.CREATED,
            actor_id=actor_id,
            payload={
                "quote_no": quote.quote_no,
                "version_no": quote.version_no,
                "currency": quote.currency,
                "line_count": len(calculation.lines),
                "grand_total": str(calculation.grand_total),
            },
        )
        if inquiry is not None:
            self._apply_inquiry_status(inquiry, InquiryStatus.QUOTE_DRAFTED)
        await self._session.flush()
        return quote

    async def submit_for_approval(
        self, *, tenant_id: uuid.UUID, quote_id: uuid.UUID, actor_id: uuid.UUID
    ) -> ApprovalTask:
        await set_tenant_context(self._session, tenant_id)
        quote = await self._get_quote(tenant_id, quote_id, for_update=True)
        self._require_status(quote, QuoteStatus.DRAFT)

        task = ApprovalTask(
            tenant_id=tenant_id,
            object_type=APPROVAL_OBJECT_TYPE,
            object_id=quote.id,
            approval_type=QUOTE_APPROVAL_TYPE,
            status=ApprovalStatus.PENDING.value,
            requested_by=actor_id,
        )
        self._session.add(task)
        quote.status = QuoteStatus.PENDING_APPROVAL.value
        await self._session.flush()

        self._add_event(
            tenant_id=tenant_id,
            quote_id=quote.id,
            event_type=QuoteEventType.SUBMITTED,
            actor_id=actor_id,
            payload={"approval_task_id": str(task.id)},
        )
        await self._advance_inquiry(tenant_id, quote.inquiry_id, InquiryStatus.PENDING_APPROVAL)
        await self._session.flush()
        return task

    async def approve(
        self,
        *,
        tenant_id: uuid.UUID,
        quote_id: uuid.UUID,
        approver_id: uuid.UUID,
        note: str | None = None,
    ) -> Quote:
        await set_tenant_context(self._session, tenant_id)
        quote = await self._get_quote(tenant_id, quote_id, for_update=True)
        self._require_status(quote, QuoteStatus.PENDING_APPROVAL)
        task = await self._get_pending_approval(tenant_id, quote.id)
        if task.requested_by == approver_id:
            raise QuoteError(
                QuoteErrorCode.SELF_APPROVAL_FORBIDDEN,
                "requester cannot approve their own quote",
            )

        task.status = ApprovalStatus.APPROVED.value
        task.approver_id = approver_id
        task.decided_at = datetime.now(UTC)
        task.decision_note = note
        quote.status = QuoteStatus.APPROVED.value
        self._add_event(
            tenant_id=tenant_id,
            quote_id=quote.id,
            event_type=QuoteEventType.APPROVED,
            actor_id=approver_id,
            payload={"approval_task_id": str(task.id), "note": note},
        )
        await self._advance_inquiry(tenant_id, quote.inquiry_id, InquiryStatus.QUOTE_APPROVED)
        await self._session.flush()
        return quote

    async def reject(
        self,
        *,
        tenant_id: uuid.UUID,
        quote_id: uuid.UUID,
        approver_id: uuid.UUID,
        note: str | None = None,
    ) -> Quote:
        await set_tenant_context(self._session, tenant_id)
        quote = await self._get_quote(tenant_id, quote_id, for_update=True)
        self._require_status(quote, QuoteStatus.PENDING_APPROVAL)
        task = await self._get_pending_approval(tenant_id, quote.id)
        if task.requested_by == approver_id:
            raise QuoteError(
                QuoteErrorCode.SELF_APPROVAL_FORBIDDEN,
                "requester cannot reject their own quote",
            )

        task.status = ApprovalStatus.REJECTED.value
        task.approver_id = approver_id
        task.decided_at = datetime.now(UTC)
        task.decision_note = note
        quote.status = QuoteStatus.REJECTED.value
        self._add_event(
            tenant_id=tenant_id,
            quote_id=quote.id,
            event_type=QuoteEventType.REJECTED,
            actor_id=approver_id,
            payload={"approval_task_id": str(task.id), "note": note},
        )
        await self._advance_inquiry(tenant_id, quote.inquiry_id, InquiryStatus.QUOTE_DRAFTED)
        await self._session.flush()
        return quote

    async def revise(
        self, *, tenant_id: uuid.UUID, quote_id: uuid.UUID, actor_id: uuid.UUID
    ) -> Quote:
        await set_tenant_context(self._session, tenant_id)
        quote = await self._get_quote(tenant_id, quote_id, for_update=True)
        self._require_status(quote, QuoteStatus.REJECTED)
        quote.status = QuoteStatus.DRAFT.value
        self._add_event(
            tenant_id=tenant_id,
            quote_id=quote.id,
            event_type=QuoteEventType.REVISED,
            actor_id=actor_id,
        )
        await self._session.flush()
        return quote

    async def cancel(
        self,
        *,
        tenant_id: uuid.UUID,
        quote_id: uuid.UUID,
        actor_id: uuid.UUID,
        note: str | None = None,
    ) -> Quote:
        await set_tenant_context(self._session, tenant_id)
        quote = await self._get_quote(tenant_id, quote_id, for_update=True)
        self._require_status(quote, QuoteStatus.DRAFT, QuoteStatus.APPROVED)
        quote.status = QuoteStatus.CANCELLED.value
        self._add_event(
            tenant_id=tenant_id,
            quote_id=quote.id,
            event_type=QuoteEventType.CANCELLED,
            actor_id=actor_id,
            payload={"note": note},
        )
        await self._session.flush()
        return quote

    async def mark_sent(
        self, *, tenant_id: uuid.UUID, quote_id: uuid.UUID, actor_id: uuid.UUID
    ) -> Quote:
        await set_tenant_context(self._session, tenant_id)
        quote = await self._get_quote(tenant_id, quote_id, for_update=True)
        self._require_status(quote, QuoteStatus.APPROVED)
        quote.status = QuoteStatus.SENT.value
        self._add_event(
            tenant_id=tenant_id,
            quote_id=quote.id,
            event_type=QuoteEventType.SENT,
            actor_id=actor_id,
        )
        await self._advance_inquiry(tenant_id, quote.inquiry_id, InquiryStatus.REPLIED)
        await self._session.flush()
        return quote

    async def expire(self, *, tenant_id: uuid.UUID, quote_id: uuid.UUID, as_of: date) -> Quote:
        await set_tenant_context(self._session, tenant_id)
        quote = await self._get_quote(tenant_id, quote_id, for_update=True)
        self._require_status(quote, QuoteStatus.APPROVED, QuoteStatus.SENT)
        if quote.valid_until is None or quote.valid_until >= as_of:
            raise QuoteError(
                QuoteErrorCode.VALIDITY_NOT_REACHED,
                "quote validity has not ended",
            )
        quote.status = QuoteStatus.EXPIRED.value
        self._add_event(
            tenant_id=tenant_id,
            quote_id=quote.id,
            event_type=QuoteEventType.EXPIRED,
            actor_id=None,
            payload={"as_of": as_of.isoformat()},
        )
        await self._session.flush()
        return quote

    async def _get_quote(
        self, tenant_id: uuid.UUID, quote_id: uuid.UUID, *, for_update: bool = False
    ) -> Quote:
        statement = select(Quote).where(
            Quote.tenant_id == tenant_id,
            Quote.id == quote_id,
        )
        if for_update:
            statement = statement.with_for_update()
        quote = await self._session.scalar(statement)
        if quote is None:
            raise QuoteError(QuoteErrorCode.QUOTE_NOT_FOUND, "quote not found")
        return quote

    async def _get_pending_approval(
        self, tenant_id: uuid.UUID, quote_id: uuid.UUID
    ) -> ApprovalTask:
        tasks = (
            await self._session.scalars(
                select(ApprovalTask)
                .where(
                    ApprovalTask.tenant_id == tenant_id,
                    ApprovalTask.object_type == APPROVAL_OBJECT_TYPE,
                    ApprovalTask.object_id == quote_id,
                    ApprovalTask.approval_type == QUOTE_APPROVAL_TYPE,
                    ApprovalTask.status == ApprovalStatus.PENDING.value,
                )
                .with_for_update()
            )
        ).all()
        if not tasks:
            raise QuoteError(
                QuoteErrorCode.APPROVAL_NOT_FOUND,
                "quote has no pending approval task",
            )
        if len(tasks) > 1:
            raise QuoteError(
                QuoteErrorCode.APPROVAL_AMBIGUOUS,
                "quote has more than one pending approval task",
            )
        return tasks[0]

    async def _load_inquiry(self, tenant_id: uuid.UUID, inquiry_id: uuid.UUID) -> Inquiry:
        inquiry = await self._session.scalar(
            select(Inquiry)
            .where(
                Inquiry.tenant_id == tenant_id,
                Inquiry.id == inquiry_id,
            )
            .with_for_update()
        )
        if inquiry is None:
            raise QuoteError(
                QuoteErrorCode.INQUIRY_NOT_FOUND,
                "inquiry not found for the tenant",
            )
        return inquiry

    async def _advance_inquiry(
        self,
        tenant_id: uuid.UUID,
        inquiry_id: uuid.UUID | None,
        target: InquiryStatus,
    ) -> None:
        if inquiry_id is None:
            return
        inquiry = await self._load_inquiry(tenant_id, inquiry_id)
        self._apply_inquiry_status(inquiry, target)

    @staticmethod
    def _apply_inquiry_status(inquiry: Inquiry, target: InquiryStatus) -> None:
        if can_transition(inquiry.status, target):
            inquiry.status = target.value

    async def _load_products(
        self, *, tenant_id: uuid.UUID, product_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, Product]:
        if not product_ids:
            return {}
        products = (
            await self._session.scalars(
                select(Product).where(
                    Product.tenant_id == tenant_id,
                    Product.id.in_(product_ids),
                )
            )
        ).all()
        by_id = {product.id: product for product in products}
        if by_id.keys() != product_ids:
            raise QuoteError(
                QuoteErrorCode.PRODUCT_NOT_FOUND,
                "one or more products were not found for the tenant",
            )
        return by_id

    def _build_item(
        self,
        *,
        quote: Quote,
        line_no: int,
        line: LineCalculation,
        product: Product,
    ) -> QuoteItem:
        return QuoteItem(
            tenant_id=quote.tenant_id,
            quote_id=quote.id,
            line_no=line_no,
            product_id=line.product_id,
            product_snapshot_json=_product_snapshot(product),
            quantity=line.requested_quantity,
            unit=line.requested_unit,
            priced_quantity=line.priced_quantity,
            price_unit=line.price_unit,
            price_basis=line.price_basis,
            unit_price=line.unit_price,
            unit_price_display=line.unit_price_display,
            line_total=line.line_total,
            line_total_display=line.line_total_display,
            price_source_ref=_price_source_ref(line.source),
        )

    def _add_event(
        self,
        *,
        tenant_id: uuid.UUID,
        quote_id: uuid.UUID,
        event_type: QuoteEventType,
        actor_id: uuid.UUID | None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        self._session.add(
            QuoteEvent(
                tenant_id=tenant_id,
                quote_id=quote_id,
                event_type=event_type.value,
                actor_id=actor_id,
                event_payload=dict(payload or {}),
            )
        )

    @staticmethod
    def _require_status(quote: Quote, *allowed: QuoteStatus) -> None:
        if quote.status not in {status.value for status in allowed}:
            raise QuoteError(
                QuoteErrorCode.INVALID_STATUS_TRANSITION,
                f"quote status {quote.status} does not allow this action",
            )


def _product_snapshot(product: Product) -> dict[str, Any]:
    return {
        "product_code": product.product_code,
        "product_name": product.product_name,
        "category": product.category,
        "standard_code": product.standard_code,
        "material": product.material,
        "grade": product.grade,
        "diameter": product.diameter,
        "length": product.length,
        "thread_pitch": product.thread_pitch,
        "head_type": product.head_type,
        "drive_type": product.drive_type,
        "surface_finish": product.surface_finish,
        "sales_unit": product.sales_unit,
        "moq": str(product.moq) if product.moq is not None else None,
        "packaging": product.packaging,
        "attributes": product.attributes,
    }


def _price_source_ref(source: PriceSource) -> dict[str, Any]:
    return {
        "kind": source.kind.value,
        "source_id": str(source.source_id),
        "version": source.version,
        "detail_id": str(source.detail_id) if source.detail_id is not None else None,
        "valid_from": source.valid_from.isoformat(),
        "valid_to": source.valid_to.isoformat() if source.valid_to is not None else None,
        "tier_valid_from": (
            source.tier_valid_from.isoformat() if source.tier_valid_from is not None else None
        ),
        "tier_valid_to": (
            source.tier_valid_to.isoformat() if source.tier_valid_to is not None else None
        ),
    }
