import os
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.tenant import set_tenant_context
from app.models.product import Product
from app.models.quote import ApprovalTask, Quote, QuoteEvent, QuoteItem
from app.models.tenant import Tenant, User
from app.pricing import (
    PriceSelection,
    PriceSource,
    PriceSourceKind,
    QuoteCalculation,
    calculate_line,
    calculate_quote,
)
from app.quotes import (
    APPROVAL_OBJECT_TYPE,
    QUOTE_APPROVAL_TYPE,
    QuoteError,
    QuoteErrorCode,
    QuoteService,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to run database integration tests",
)


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            factory = async_sessionmaker(bind=connection, expire_on_commit=False)
            async with factory() as session:
                yield session
            await transaction.rollback()
    finally:
        await engine.dispose()


async def seed_tenant(session: AsyncSession, slug: str) -> tuple[Tenant, User, User, Product]:
    tenant = Tenant(name=slug, slug=slug)
    session.add(tenant)
    await session.flush()
    await set_tenant_context(session, tenant.id)

    requester = User(
        email=f"rep@{slug}.example",
        password_hash="x",
        display_name="Sales Rep",
    )
    approver = User(
        email=f"approver@{slug}.example",
        password_hash="x",
        display_name="Approver",
    )
    product = Product(
        tenant_id=tenant.id,
        product_code="BOLT-M8-30",
        product_name="Hex bolt M8x30 SS304",
        category="BOLT",
        sales_unit="PCS",
        moq=Decimal("1000"),
    )
    session.add_all([requester, approver, product])
    await session.flush()
    return tenant, requester, approver, product


def make_calculation(
    product_id: uuid.UUID,
    *,
    quantity: str = "1000",
    unit_price: str = "2.2000",
) -> QuoteCalculation:
    selection = PriceSelection(
        product_id=product_id,
        currency="USD",
        unit_price=Decimal(unit_price),
        price_basis="PER_PIECE",
        price_unit="PCS",
        source=PriceSource(
            kind=PriceSourceKind.PRICE_LIST,
            source_id=uuid.uuid4(),
            valid_from=date(2026, 1, 1),
            valid_to=None,
            version=1,
            detail_id=uuid.uuid4(),
        ),
    )
    line = calculate_line(selection, quantity=Decimal(quantity), unit="PCS")
    return calculate_quote([line])


async def create_draft(
    session: AsyncSession,
    tenant: Tenant,
    requester: User,
    product: Product,
    *,
    quote_no: str = "Q-2026-0001",
    version_no: int = 1,
    valid_until: date | None = None,
    calculation: QuoteCalculation | None = None,
) -> Quote:
    service = QuoteService(session)
    return await service.create_draft(
        tenant_id=tenant.id,
        actor_id=requester.id,
        quote_no=quote_no,
        calculation=calculation or make_calculation(product.id),
        version_no=version_no,
        valid_until=valid_until,
        terms={"payment": "T/T 30% deposit"},
        source_snapshot={"engine": "v1"},
    )


async def events_for(session: AsyncSession, quote_id: uuid.UUID) -> list[QuoteEvent]:
    result = await session.scalars(
        select(QuoteEvent).where(QuoteEvent.quote_id == quote_id).order_by(QuoteEvent.created_at)
    )
    return list(result)


async def test_create_draft_persists_quote_items_and_snapshots(session: AsyncSession) -> None:
    tenant, requester, _, product = await seed_tenant(session, "create-draft")

    quote = await create_draft(
        session,
        tenant,
        requester,
        product,
        valid_until=date(2026, 12, 31),
    )

    assert quote.tenant_id == tenant.id
    assert quote.status == "DRAFT"
    assert quote.version_no == 1
    assert quote.currency == "USD"
    assert quote.subtotal == Decimal("2200.0000")
    assert quote.grand_total == Decimal("2200.0000")
    assert quote.grand_total_display == Decimal("2200.00")
    assert quote.valid_until == date(2026, 12, 31)
    assert quote.terms_json == {"payment": "T/T 30% deposit"}
    assert quote.source_snapshot_json == {"engine": "v1"}
    assert quote.created_by == requester.id

    items = (await session.scalars(select(QuoteItem).where(QuoteItem.quote_id == quote.id))).all()
    assert len(items) == 1
    item = items[0]
    assert item.line_no == 1
    assert item.product_id == product.id
    assert item.quantity == Decimal("1000.0000")
    assert item.unit == "PCS"
    assert item.priced_quantity == Decimal("1000.0000")
    assert item.unit_price == Decimal("2.2000")
    assert item.line_total == Decimal("2200.0000")
    assert item.product_snapshot_json["product_code"] == "BOLT-M8-30"
    assert item.product_snapshot_json["product_name"] == "Hex bolt M8x30 SS304"
    assert item.price_source_ref["kind"] == "PRICE_LIST"
    assert item.price_source_ref["version"] == 1

    events = await events_for(session, quote.id)
    assert [event.event_type for event in events] == ["CREATED"]
    assert events[0].actor_id == requester.id
    assert events[0].event_payload["line_count"] == 1
    assert events[0].event_payload["grand_total"] == "2200.0000"


async def test_create_draft_rejects_duplicate_version(session: AsyncSession) -> None:
    tenant, requester, _, product = await seed_tenant(session, "duplicate-version")
    await create_draft(session, tenant, requester, product, quote_no="Q-DUP")

    with pytest.raises(QuoteError) as exc_info:
        await create_draft(session, tenant, requester, product, quote_no="Q-DUP")

    assert exc_info.value.code == QuoteErrorCode.QUOTE_VERSION_EXISTS


async def test_create_draft_allows_next_version(session: AsyncSession) -> None:
    tenant, requester, _, product = await seed_tenant(session, "next-version")
    first = await create_draft(session, tenant, requester, product, quote_no="Q-VER")
    second = await create_draft(session, tenant, requester, product, quote_no="Q-VER", version_no=2)

    assert second.id != first.id
    assert second.version_no == 2
    assert first.version_no == 1


async def test_create_draft_requires_at_least_one_line(session: AsyncSession) -> None:
    tenant, requester, _, product = await seed_tenant(session, "empty-quote")
    empty = QuoteCalculation(
        currency="USD",
        subtotal=Decimal("0"),
        subtotal_display=Decimal("0"),
        discount_total=Decimal("0"),
        discount_total_display=Decimal("0"),
        freight_total=Decimal("0"),
        freight_total_display=Decimal("0"),
        other_charges=Decimal("0"),
        other_charges_display=Decimal("0"),
        grand_total=Decimal("0"),
        grand_total_display=Decimal("0"),
        lines=(),
    )

    with pytest.raises(QuoteError) as exc_info:
        await create_draft(
            session,
            tenant,
            requester,
            product,
            calculation=empty,
        )

    assert exc_info.value.code == QuoteErrorCode.QUOTE_EMPTY


async def test_create_draft_rejects_blank_quote_no(session: AsyncSession) -> None:
    tenant, requester, _, product = await seed_tenant(session, "blank-quote-no")

    with pytest.raises(QuoteError) as exc_info:
        await create_draft(session, tenant, requester, product, quote_no="   ")

    assert exc_info.value.code == QuoteErrorCode.INVALID_QUOTE_NO


async def test_create_draft_rejects_product_from_another_tenant(
    session: AsyncSession,
) -> None:
    tenant_a, requester_a, _, _ = await seed_tenant(session, "item-tenant-a")
    _, _, _, product_b = await seed_tenant(session, "item-tenant-b")

    with pytest.raises(QuoteError) as exc_info:
        await create_draft(
            session,
            tenant_a,
            requester_a,
            product_b,
            calculation=make_calculation(product_b.id),
        )

    assert exc_info.value.code == QuoteErrorCode.PRODUCT_NOT_FOUND


async def test_submit_creates_pending_approval_task(session: AsyncSession) -> None:
    tenant, requester, _, product = await seed_tenant(session, "submit")
    quote = await create_draft(session, tenant, requester, product)
    service = QuoteService(session)

    task = await service.submit_for_approval(
        tenant_id=tenant.id, quote_id=quote.id, actor_id=requester.id
    )

    assert quote.status == "PENDING_APPROVAL"
    assert task.status == "PENDING"
    assert task.object_type == APPROVAL_OBJECT_TYPE
    assert task.object_id == quote.id
    assert task.approval_type == QUOTE_APPROVAL_TYPE
    assert task.requested_by == requester.id
    assert task.approver_id is None
    assert task.decided_at is None

    events = await events_for(session, quote.id)
    assert [event.event_type for event in events] == ["CREATED", "SUBMITTED"]
    assert events[1].event_payload["approval_task_id"] == str(task.id)


async def test_requester_cannot_approve_own_quote(session: AsyncSession) -> None:
    tenant, requester, _, product = await seed_tenant(session, "self-approval")
    quote = await create_draft(session, tenant, requester, product)
    service = QuoteService(session)
    task = await service.submit_for_approval(
        tenant_id=tenant.id, quote_id=quote.id, actor_id=requester.id
    )

    with pytest.raises(QuoteError) as exc_info:
        await service.approve(tenant_id=tenant.id, quote_id=quote.id, approver_id=requester.id)

    assert exc_info.value.code == QuoteErrorCode.SELF_APPROVAL_FORBIDDEN
    assert quote.status == "PENDING_APPROVAL"
    assert task.status == "PENDING"
    assert task.approver_id is None


async def test_approval_updates_task_and_quote(session: AsyncSession) -> None:
    tenant, requester, approver, product = await seed_tenant(session, "approve")
    quote = await create_draft(session, tenant, requester, product)
    service = QuoteService(session)
    task = await service.submit_for_approval(
        tenant_id=tenant.id, quote_id=quote.id, actor_id=requester.id
    )

    await service.approve(
        tenant_id=tenant.id,
        quote_id=quote.id,
        approver_id=approver.id,
        note="prices verified",
    )

    assert quote.status == "APPROVED"
    assert task.status == "APPROVED"
    assert task.approver_id == approver.id
    assert task.decided_at is not None
    assert task.decision_note == "prices verified"

    events = await events_for(session, quote.id)
    assert [event.event_type for event in events] == ["CREATED", "SUBMITTED", "APPROVED"]
    assert events[-1].actor_id == approver.id
    assert events[-1].event_payload["note"] == "prices verified"


async def test_rejection_then_revision_allows_resubmission(session: AsyncSession) -> None:
    tenant, requester, approver, product = await seed_tenant(session, "reject")
    quote = await create_draft(session, tenant, requester, product)
    service = QuoteService(session)
    first_task = await service.submit_for_approval(
        tenant_id=tenant.id, quote_id=quote.id, actor_id=requester.id
    )

    await service.reject(
        tenant_id=tenant.id,
        quote_id=quote.id,
        approver_id=approver.id,
        note="discount too high",
    )

    assert quote.status == "REJECTED"
    assert first_task.status == "REJECTED"
    assert first_task.decision_note == "discount too high"

    await service.revise(tenant_id=tenant.id, quote_id=quote.id, actor_id=requester.id)
    assert quote.status == "DRAFT"

    second_task = await service.submit_for_approval(
        tenant_id=tenant.id, quote_id=quote.id, actor_id=requester.id
    )
    assert second_task.id != first_task.id
    assert second_task.status == "PENDING"

    pending = (
        await session.scalars(
            select(ApprovalTask).where(
                ApprovalTask.object_id == quote.id,
                ApprovalTask.status == "PENDING",
            )
        )
    ).all()
    assert [task.id for task in pending] == [second_task.id]

    events = await events_for(session, quote.id)
    assert [event.event_type for event in events] == [
        "CREATED",
        "SUBMITTED",
        "REJECTED",
        "REVISED",
        "SUBMITTED",
    ]


async def test_cannot_approve_a_draft(session: AsyncSession) -> None:
    tenant, requester, approver, product = await seed_tenant(session, "approve-draft")
    quote = await create_draft(session, tenant, requester, product)
    service = QuoteService(session)

    with pytest.raises(QuoteError) as exc_info:
        await service.approve(tenant_id=tenant.id, quote_id=quote.id, approver_id=approver.id)

    assert exc_info.value.code == QuoteErrorCode.INVALID_STATUS_TRANSITION
    assert quote.status == "DRAFT"


async def test_approval_requires_pending_task(session: AsyncSession) -> None:
    tenant, requester, approver, product = await seed_tenant(session, "approval-missing")
    quote = await create_draft(session, tenant, requester, product)
    service = QuoteService(session)
    await service.submit_for_approval(tenant_id=tenant.id, quote_id=quote.id, actor_id=requester.id)
    task = (
        await session.scalars(select(ApprovalTask).where(ApprovalTask.object_id == quote.id))
    ).one()
    task.status = "CANCELLED"
    await session.flush()

    with pytest.raises(QuoteError) as exc_info:
        await service.approve(tenant_id=tenant.id, quote_id=quote.id, approver_id=approver.id)

    assert exc_info.value.code == QuoteErrorCode.APPROVAL_NOT_FOUND
    assert quote.status == "PENDING_APPROVAL"


async def test_mark_sent_requires_approved_status(session: AsyncSession) -> None:
    tenant, requester, approver, product = await seed_tenant(session, "send")
    quote = await create_draft(session, tenant, requester, product)
    service = QuoteService(session)

    with pytest.raises(QuoteError) as exc_info:
        await service.mark_sent(tenant_id=tenant.id, quote_id=quote.id, actor_id=requester.id)
    assert exc_info.value.code == QuoteErrorCode.INVALID_STATUS_TRANSITION

    await service.submit_for_approval(tenant_id=tenant.id, quote_id=quote.id, actor_id=requester.id)
    await service.approve(tenant_id=tenant.id, quote_id=quote.id, approver_id=approver.id)
    await service.mark_sent(tenant_id=tenant.id, quote_id=quote.id, actor_id=requester.id)

    assert quote.status == "SENT"
    events = await events_for(session, quote.id)
    assert [event.event_type for event in events] == [
        "CREATED",
        "SUBMITTED",
        "APPROVED",
        "SENT",
    ]


async def test_cancel_from_draft_and_approved(session: AsyncSession) -> None:
    tenant, requester, approver, product = await seed_tenant(session, "cancel")
    service = QuoteService(session)
    draft = await create_draft(session, tenant, requester, product, quote_no="Q-CANCEL-1")
    approved = await create_draft(session, tenant, requester, product, quote_no="Q-CANCEL-2")
    await service.submit_for_approval(
        tenant_id=tenant.id, quote_id=approved.id, actor_id=requester.id
    )
    await service.approve(tenant_id=tenant.id, quote_id=approved.id, approver_id=approver.id)

    await service.cancel(tenant_id=tenant.id, quote_id=draft.id, actor_id=requester.id)
    await service.cancel(
        tenant_id=tenant.id,
        quote_id=approved.id,
        actor_id=requester.id,
        note="customer withdrew",
    )

    assert draft.status == "CANCELLED"
    assert approved.status == "CANCELLED"
    assert (await events_for(session, approved.id))[-1].event_type == "CANCELLED"


async def test_cannot_cancel_a_sent_quote(session: AsyncSession) -> None:
    tenant, requester, approver, product = await seed_tenant(session, "cancel-sent")
    quote = await create_draft(session, tenant, requester, product)
    service = QuoteService(session)
    await service.submit_for_approval(tenant_id=tenant.id, quote_id=quote.id, actor_id=requester.id)
    await service.approve(tenant_id=tenant.id, quote_id=quote.id, approver_id=approver.id)
    await service.mark_sent(tenant_id=tenant.id, quote_id=quote.id, actor_id=requester.id)

    with pytest.raises(QuoteError) as exc_info:
        await service.cancel(tenant_id=tenant.id, quote_id=quote.id, actor_id=requester.id)

    assert exc_info.value.code == QuoteErrorCode.INVALID_STATUS_TRANSITION
    assert quote.status == "SENT"


async def test_expire_requires_elapsed_validity(session: AsyncSession) -> None:
    tenant, requester, approver, product = await seed_tenant(session, "expire")
    service = QuoteService(session)
    quote = await create_draft(session, tenant, requester, product, valid_until=date(2026, 10, 31))
    await service.submit_for_approval(tenant_id=tenant.id, quote_id=quote.id, actor_id=requester.id)
    await service.approve(tenant_id=tenant.id, quote_id=quote.id, approver_id=approver.id)

    with pytest.raises(QuoteError) as exc_info:
        await service.expire(tenant_id=tenant.id, quote_id=quote.id, as_of=date(2026, 10, 31))
    assert exc_info.value.code == QuoteErrorCode.VALIDITY_NOT_REACHED

    await service.expire(tenant_id=tenant.id, quote_id=quote.id, as_of=date(2026, 11, 1))
    assert quote.status == "EXPIRED"
    event = (await events_for(session, quote.id))[-1]
    assert event.event_type == "EXPIRED"
    assert event.actor_id is None
    assert event.event_payload == {"as_of": "2026-11-01"}


async def test_quote_without_validity_cannot_expire(session: AsyncSession) -> None:
    tenant, requester, approver, product = await seed_tenant(session, "no-validity")
    quote = await create_draft(session, tenant, requester, product)
    service = QuoteService(session)
    await service.submit_for_approval(tenant_id=tenant.id, quote_id=quote.id, actor_id=requester.id)
    await service.approve(tenant_id=tenant.id, quote_id=quote.id, approver_id=approver.id)

    with pytest.raises(QuoteError) as exc_info:
        await service.expire(tenant_id=tenant.id, quote_id=quote.id, as_of=date(2026, 11, 1))

    assert exc_info.value.code == QuoteErrorCode.VALIDITY_NOT_REACHED


async def test_quotes_are_not_visible_across_tenants(session: AsyncSession) -> None:
    tenant_a, requester_a, approver_a, product_a = await seed_tenant(session, "iso-a")
    tenant_b, requester_b, _, _ = await seed_tenant(session, "iso-b")
    quote = await create_draft(session, tenant_a, requester_a, product_a)
    service = QuoteService(session)

    with pytest.raises(QuoteError) as submit_error:
        await service.submit_for_approval(
            tenant_id=tenant_b.id, quote_id=quote.id, actor_id=requester_b.id
        )
    assert submit_error.value.code == QuoteErrorCode.QUOTE_NOT_FOUND

    await service.submit_for_approval(
        tenant_id=tenant_a.id, quote_id=quote.id, actor_id=requester_a.id
    )

    with pytest.raises(QuoteError) as approve_error:
        await service.approve(tenant_id=tenant_b.id, quote_id=quote.id, approver_id=requester_b.id)
    assert approve_error.value.code == QuoteErrorCode.QUOTE_NOT_FOUND

    await service.approve(tenant_id=tenant_a.id, quote_id=quote.id, approver_id=approver_a.id)
    assert quote.status == "APPROVED"


async def test_full_lifecycle_records_ordered_audit_events(session: AsyncSession) -> None:
    tenant, requester, approver, product = await seed_tenant(session, "lifecycle")
    quote = await create_draft(session, tenant, requester, product, valid_until=date(2026, 10, 31))
    service = QuoteService(session)
    await service.submit_for_approval(tenant_id=tenant.id, quote_id=quote.id, actor_id=requester.id)
    await service.approve(tenant_id=tenant.id, quote_id=quote.id, approver_id=approver.id)
    await service.mark_sent(tenant_id=tenant.id, quote_id=quote.id, actor_id=requester.id)
    await service.expire(tenant_id=tenant.id, quote_id=quote.id, as_of=date(2026, 11, 2))

    events = await events_for(session, quote.id)

    assert [event.event_type for event in events] == [
        "CREATED",
        "SUBMITTED",
        "APPROVED",
        "SENT",
        "EXPIRED",
    ]
    timestamps = [event.created_at for event in events]
    assert timestamps == sorted(timestamps)
    assert all(event.tenant_id == tenant.id for event in events)
