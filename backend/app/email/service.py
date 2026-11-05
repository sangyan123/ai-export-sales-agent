import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.email import (
    EmailGenerationError,
    EmailGenerationErrorCode,
    EmailGenerationInput,
    EmailGenerator,
    EmailQuote,
    EmailQuoteItem,
    get_email_generator,
)
from app.ai.usage import LLMUsage
from app.core.config import settings
from app.db.tenant import set_tenant_context
from app.email import EmailError, EmailErrorCode, EmailStatus
from app.inquiries.requirements import requirement_values
from app.models.customer import Customer
from app.models.ai_usage import AIUsageRecord
from app.models.email import EmailDraft
from app.models.inquiry import Inquiry, InquiryRequirement
from app.models.quote import Quote, QuoteItem
from app.quotes import QuoteStatus


class EmailDraftService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        generator: EmailGenerator | None = None,
    ) -> None:
        self._session = session
        self._generator = generator

    async def generate(
        self,
        *,
        tenant_id: uuid.UUID,
        inquiry_id: uuid.UUID,
        quote_id: uuid.UUID | None = None,
        language: str = "en",
    ) -> EmailDraft:
        await set_tenant_context(self._session, tenant_id)
        inquiry = await self._session.scalar(
            select(Inquiry)
            .where(Inquiry.tenant_id == tenant_id, Inquiry.id == inquiry_id)
            .with_for_update()
        )
        if inquiry is None:
            raise EmailError(EmailErrorCode.INQUIRY_NOT_FOUND, "inquiry not found")

        quote = await self._resolve_quote(tenant_id, inquiry_id, quote_id)
        items = list(
            await self._session.scalars(
                select(QuoteItem)
                .where(QuoteItem.tenant_id == tenant_id, QuoteItem.quote_id == quote.id)
                .order_by(QuoteItem.line_no)
            )
        )
        requirement = await self._session.scalar(
            select(InquiryRequirement)
            .where(
                InquiryRequirement.tenant_id == tenant_id,
                InquiryRequirement.inquiry_id == inquiry_id,
            )
            .order_by(InquiryRequirement.schema_version.desc())
            .limit(1)
        )
        customer = await self._session.scalar(
            select(Customer).where(
                Customer.tenant_id == tenant_id,
                Customer.id == inquiry.customer_id,
            )
        )

        values = requirement_values(requirement) if requirement else {}
        missing_requirements = _missing_requirements(requirement, values)
        generation_input = EmailGenerationInput(
            inquiry_subject=inquiry.subject,
            inquiry_raw_body=inquiry.raw_body,
            customer_company=customer.company_name if customer else "Customer",
            requirements=values,
            missing_requirements=missing_requirements,
            quote=_quote_input(quote),
            items=tuple(_item_input(item) for item in items),
            language=language.lower(),
        )
        generator = self._generator or get_email_generator()
        captured: list[LLMUsage] = []

        async def usage_sink(usage: LLMUsage) -> None:
            captured.append(usage)

        try:
            content = await generator.generate(generation_input, usage_sink=usage_sink)
        except EmailGenerationError as exc:
            if exc.code is EmailGenerationErrorCode.UNSUPPORTED_LANGUAGE:
                raise EmailError(EmailErrorCode.EMAIL_UNSUPPORTED_LANGUAGE, exc.message) from exc
            raise

        if captured:
            usage = captured[-1]
            self._session.add(
                AIUsageRecord(
                    tenant_id=tenant_id,
                    operation_type="EMAIL_GENERATE",
                    model_id=usage.model_id,
                    provider=settings.llm_provider or "deterministic",
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    total_tokens=usage.total_tokens,
                    duration_ms=usage.duration_ms,
                    status="SUCCESS",
                    requested_by=None,
                    finished_at=datetime.now(UTC),
                )
            )

        draft = EmailDraft(
            tenant_id=tenant_id,
            inquiry_id=inquiry_id,
            quote_id=quote.id,
            subject=content.subject,
            body=content.body,
            language=generation_input.language,
            status=EmailStatus.DRAFT.value,
            model_id=generator.model_id,
            claims_json=content.claims_used,
            missing_information_json=content.missing_information,
            review_flags_json=content.review_flags,
        )
        self._session.add(draft)
        await self._session.flush()
        return draft

    async def get(self, *, tenant_id: uuid.UUID, draft_id: uuid.UUID) -> EmailDraft:
        await set_tenant_context(self._session, tenant_id)
        draft = await self._session.scalar(
            select(EmailDraft).where(
                EmailDraft.tenant_id == tenant_id,
                EmailDraft.id == draft_id,
            )
        )
        if draft is None:
            raise EmailError(EmailErrorCode.EMAIL_DRAFT_NOT_FOUND, "email draft not found")
        return draft

    async def update(
        self,
        *,
        tenant_id: uuid.UUID,
        draft_id: uuid.UUID,
        subject: str | None,
        body: str | None,
    ) -> EmailDraft:
        await set_tenant_context(self._session, tenant_id)
        draft = await self._session.scalar(
            select(EmailDraft)
            .where(
                EmailDraft.tenant_id == tenant_id,
                EmailDraft.id == draft_id,
            )
            .with_for_update()
        )
        if draft is None:
            raise EmailError(EmailErrorCode.EMAIL_DRAFT_NOT_FOUND, "email draft not found")
        if draft.status != EmailStatus.DRAFT.value:
            raise EmailError(
                EmailErrorCode.EMAIL_DRAFT_NOT_EDITABLE,
                f"email draft status {draft.status} does not allow editing",
            )
        if subject is not None:
            draft.subject = subject.strip()
        if body is not None:
            draft.body = body.strip()
        await self._session.flush()
        await self._session.refresh(draft)
        return draft

    async def approve(
        self,
        *,
        tenant_id: uuid.UUID,
        draft_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> EmailDraft:
        await set_tenant_context(self._session, tenant_id)
        draft = await self._session.scalar(
            select(EmailDraft)
            .where(
                EmailDraft.tenant_id == tenant_id,
                EmailDraft.id == draft_id,
            )
            .with_for_update()
        )
        if draft is None:
            raise EmailError(EmailErrorCode.EMAIL_DRAFT_NOT_FOUND, "email draft not found")
        if draft.status != EmailStatus.DRAFT.value:
            raise EmailError(
                EmailErrorCode.EMAIL_DRAFT_NOT_APPROVABLE,
                f"email draft status {draft.status} does not allow approval",
            )
        quote = await self._session.scalar(
            select(Quote).where(Quote.tenant_id == tenant_id, Quote.id == draft.quote_id)
        )
        if quote is None or quote.status != QuoteStatus.APPROVED.value:
            raise EmailError(
                EmailErrorCode.EMAIL_QUOTE_NOT_APPROVED,
                "email draft can only be approved while its quote is approved",
            )
        draft.status = EmailStatus.APPROVED.value
        draft.approved_by = actor_id
        draft.approved_at = datetime.now(UTC)
        await self._session.flush()
        await self._session.refresh(draft)
        return draft

    async def _resolve_quote(
        self,
        tenant_id: uuid.UUID,
        inquiry_id: uuid.UUID,
        quote_id: uuid.UUID | None,
    ) -> Quote:
        stmt = select(Quote).where(Quote.tenant_id == tenant_id, Quote.inquiry_id == inquiry_id)
        if quote_id is not None:
            stmt = stmt.where(Quote.id == quote_id)
        else:
            stmt = stmt.where(Quote.status == QuoteStatus.APPROVED.value).order_by(
                Quote.created_at.desc(), Quote.version_no.desc()
            )
        quote = await self._session.scalar(stmt.limit(1))
        if quote is None:
            if quote_id is not None:
                raise EmailError(EmailErrorCode.EMAIL_QUOTE_NOT_FOUND, "quote not found")
            raise EmailError(
                EmailErrorCode.EMAIL_QUOTE_NOT_APPROVED,
                "inquiry has no approved quote to build an email draft",
            )
        if quote.status != QuoteStatus.APPROVED.value:
            raise EmailError(
                EmailErrorCode.EMAIL_QUOTE_NOT_APPROVED,
                f"quote status {quote.status} does not allow email drafting",
            )
        return quote


def _missing_requirements(
    requirement: InquiryRequirement | None,
    values: dict[str, str],
) -> tuple[str, ...]:
    if requirement is None:
        return ()
    parsed = requirement.parsed_json or {}
    raw = parsed.get("missing_fields")
    if not isinstance(raw, list):
        return ()
    return tuple(name for name in raw if isinstance(name, str) and not values.get(name))


def _quote_input(quote: Quote) -> EmailQuote:
    terms = quote.terms_json or {}
    return EmailQuote(
        quote_no=quote.quote_no,
        version_no=quote.version_no,
        currency=quote.currency,
        subtotal=_decimal(quote.subtotal_display),
        discount_total=_decimal(quote.discount_total_display),
        freight_total=_decimal(quote.freight_total_display),
        grand_total=_decimal(quote.grand_total_display),
        valid_until=quote.valid_until.isoformat() if quote.valid_until else None,
        incoterm=_term(terms, "incoterm"),
        payment_terms=_term(terms, "payment_terms"),
        lead_time=_term(terms, "lead_time"),
    )


def _item_input(item: QuoteItem) -> EmailQuoteItem:
    snapshot = item.product_snapshot_json or {}
    return EmailQuoteItem(
        product_code=_text(snapshot.get("product_code")) or str(item.product_id or "N/A"),
        product_name=_text(snapshot.get("product_name")) or "Product",
        standard_code=_text(snapshot.get("standard_code")),
        material=_text(snapshot.get("material")),
        grade=_text(snapshot.get("grade")),
        diameter=_text(snapshot.get("diameter")),
        length=_text(snapshot.get("length")),
        thread_pitch=_text(snapshot.get("thread_pitch")),
        surface_finish=_text(snapshot.get("surface_finish")),
        quantity=_decimal(item.quantity),
        unit=item.unit,
        price_unit=item.price_unit,
        unit_price=_decimal(item.unit_price_display),
        line_total=_decimal(item.line_total_display),
        price_basis=item.price_basis,
    )


def _decimal(value: Decimal | None) -> str:
    return format(value, "f") if value is not None else "0"


def _term(terms: dict[str, object], key: str) -> str | None:
    value = terms.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return None
