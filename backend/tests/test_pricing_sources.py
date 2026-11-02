import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

import pytest

from app.pricing import (
    CustomerOverrideSource,
    PriceCandidate,
    PriceListSource,
    PriceResolver,
    PriceSourceKind,
    PricingError,
    PricingErrorCode,
)

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-00000000000a")
CUSTOMER_ID = uuid.UUID("00000000-0000-0000-0000-00000000000c")
PRODUCT_ID = uuid.UUID("00000000-0000-0000-0000-00000000000b")
AS_OF = date(2026, 11, 1)


def make_candidate(
    *,
    source_kind: PriceSourceKind = PriceSourceKind.PRICE_LIST,
    source_id: uuid.UUID | None = None,
    currency: str = "USD",
    min_quantity: str = "1",
    max_quantity: str | None = None,
    unit_price: str = "2.0000",
    status: str = "ACTIVE",
    valid_from: date = date(2026, 1, 1),
    valid_to: date | None = None,
) -> PriceCandidate:
    return PriceCandidate(
        product_id=PRODUCT_ID,
        currency=currency,
        min_quantity=Decimal(min_quantity),
        max_quantity=Decimal(max_quantity) if max_quantity is not None else None,
        unit_price=Decimal(unit_price),
        price_basis="PER_PIECE",
        unit="PCS",
        source_kind=source_kind,
        source_id=source_id or uuid.uuid4(),
        source_status=status,
        source_valid_from=valid_from,
        source_valid_to=valid_to,
        source_version=1,
        source_detail_id=uuid.uuid4(),
    )


class FakeSource:
    def __init__(
        self,
        name: str,
        *,
        candidates: Sequence[PriceCandidate] = (),
        error: PricingError | None = None,
    ) -> None:
        self.name = name
        self._candidates = list(candidates)
        self._error = error
        self.calls = 0

    async def candidates(
        self,
        *,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID | None,
        product_id: uuid.UUID,
        currency: str,
        as_of: date,
    ) -> Sequence[PriceCandidate]:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._candidates


class FakeRepository:
    def __init__(self, candidates: Sequence[PriceCandidate]) -> None:
        self._candidates = list(candidates)

    async def list_price_tier_candidates(
        self, *, tenant_id: uuid.UUID, product_id: uuid.UUID
    ) -> Sequence[PriceCandidate]:
        return self._candidates


class FakeOverrideRepository:
    def __init__(self, candidates: Sequence[PriceCandidate]) -> None:
        self._candidates = list(candidates)
        self.calls = 0

    async def list_customer_override_candidates(
        self, *, tenant_id: uuid.UUID, customer_id: uuid.UUID, product_id: uuid.UUID
    ) -> Sequence[PriceCandidate]:
        self.calls += 1
        return self._candidates


async def resolve_with(
    providers: Sequence[FakeSource],
    quantity: str = "10",
    customer_id: uuid.UUID | None = None,
    currency: str = "USD",
):
    resolver = PriceResolver(providers)
    return await resolver.resolve(
        tenant_id=TENANT_ID,
        customer_id=customer_id,
        product_id=PRODUCT_ID,
        quantity=Decimal(quantity),
        currency=currency,
        as_of=AS_OF,
    )


async def test_first_source_wins_and_lower_priority_sources_are_not_queried() -> None:
    override = FakeSource("customer_override", candidates=[make_candidate(unit_price="1.5000")])
    price_list = FakeSource("price_list", candidates=[make_candidate(unit_price="2.0000")])

    selection = await resolve_with([override, price_list])

    assert selection.unit_price == Decimal("1.5000")
    assert price_list.calls == 0


async def test_falls_back_when_higher_priority_source_has_no_price() -> None:
    override = FakeSource("customer_override")
    price_list = FakeSource("price_list", candidates=[make_candidate(unit_price="2.0000")])

    selection = await resolve_with([override, price_list])

    assert selection.unit_price == Decimal("2.0000")
    assert price_list.calls == 1


async def test_falls_back_when_higher_priority_source_is_expired() -> None:
    expired = FakeSource(
        "customer_override",
        candidates=[make_candidate(valid_to=date(2026, 10, 31))],
    )
    price_list = FakeSource("price_list", candidates=[make_candidate(unit_price="2.0000")])

    selection = await resolve_with([expired, price_list])

    assert selection.unit_price == Decimal("2.0000")


async def test_falls_back_when_source_raises_currency_mismatch() -> None:
    overriding = FakeSource(
        "customer_override",
        error=PricingError(PricingErrorCode.CURRENCY_MISMATCH, "no price in USD"),
    )
    price_list = FakeSource("price_list", candidates=[make_candidate(unit_price="2.0000")])

    selection = await resolve_with([overriding, price_list])

    assert selection.unit_price == Decimal("2.0000")


async def test_does_not_fall_back_on_ambiguous_tiers() -> None:
    ambiguous = FakeSource(
        "customer_override",
        candidates=[
            make_candidate(min_quantity="1", max_quantity="100"),
            make_candidate(min_quantity="50", max_quantity="200"),
        ],
    )
    price_list = FakeSource("price_list", candidates=[make_candidate()])

    with pytest.raises(PricingError) as exc_info:
        await resolve_with([ambiguous, price_list])

    assert exc_info.value.code == PricingErrorCode.TIER_AMBIGUOUS
    assert price_list.calls == 0


async def test_exhausted_sources_report_last_reason_with_attempts() -> None:
    override = FakeSource(
        "customer_override", error=PricingError(PricingErrorCode.PRICE_MISSING, "no override")
    )
    price_list = FakeSource("price_list", candidates=[make_candidate(min_quantity="100")])

    with pytest.raises(PricingError) as exc_info:
        await resolve_with([override, price_list], quantity="10")

    error = exc_info.value
    assert error.code == PricingErrorCode.NO_ELIGIBLE_TIER
    assert "customer_override:PRICE_MISSING" in error.message
    assert "price_list:NO_ELIGIBLE_TIER" in error.message
    assert isinstance(error.__cause__, PricingError)


def test_resolver_requires_at_least_one_source() -> None:
    with pytest.raises(ValueError):
        PriceResolver([])


async def test_customer_override_source_skips_lookup_without_customer() -> None:
    repository = FakeOverrideRepository([make_candidate()])
    source = CustomerOverrideSource(repository)

    candidates = await source.candidates(
        tenant_id=TENANT_ID,
        customer_id=None,
        product_id=PRODUCT_ID,
        currency="USD",
        as_of=AS_OF,
    )

    assert candidates == ()
    assert repository.calls == 0


async def test_customer_override_source_filters_by_currency() -> None:
    repository = FakeOverrideRepository(
        [
            make_candidate(source_kind=PriceSourceKind.CUSTOMER_OVERRIDE, currency="USD"),
            make_candidate(source_kind=PriceSourceKind.CUSTOMER_OVERRIDE, currency="EUR"),
        ]
    )
    source = CustomerOverrideSource(repository)

    candidates = await source.candidates(
        tenant_id=TENANT_ID,
        customer_id=CUSTOMER_ID,
        product_id=PRODUCT_ID,
        currency="eur",
        as_of=AS_OF,
    )

    assert [c.currency for c in candidates] == ["EUR"]


async def test_customer_override_source_reports_currency_mismatch() -> None:
    source = CustomerOverrideSource(
        FakeOverrideRepository(
            [make_candidate(source_kind=PriceSourceKind.CUSTOMER_OVERRIDE, currency="USD")]
        )
    )

    with pytest.raises(PricingError) as exc_info:
        await source.candidates(
            tenant_id=TENANT_ID,
            customer_id=CUSTOMER_ID,
            product_id=PRODUCT_ID,
            currency="EUR",
            as_of=AS_OF,
        )

    assert exc_info.value.code == PricingErrorCode.CURRENCY_MISMATCH


async def test_customer_override_source_rejects_two_valid_overrides() -> None:
    source = CustomerOverrideSource(
        FakeOverrideRepository(
            [
                make_candidate(source_kind=PriceSourceKind.CUSTOMER_OVERRIDE),
                make_candidate(source_kind=PriceSourceKind.CUSTOMER_OVERRIDE),
            ]
        )
    )

    with pytest.raises(PricingError) as exc_info:
        await source.candidates(
            tenant_id=TENANT_ID,
            customer_id=CUSTOMER_ID,
            product_id=PRODUCT_ID,
            currency="USD",
            as_of=AS_OF,
        )

    assert exc_info.value.code == PricingErrorCode.CUSTOMER_PRICE_AMBIGUOUS


async def test_customer_override_source_ignores_expired_override_for_ambiguity() -> None:
    source = CustomerOverrideSource(
        FakeOverrideRepository(
            [
                make_candidate(source_kind=PriceSourceKind.CUSTOMER_OVERRIDE),
                make_candidate(
                    source_kind=PriceSourceKind.CUSTOMER_OVERRIDE,
                    valid_to=date(2026, 10, 31),
                ),
            ]
        )
    )

    candidates = await source.candidates(
        tenant_id=TENANT_ID,
        customer_id=CUSTOMER_ID,
        product_id=PRODUCT_ID,
        currency="USD",
        as_of=AS_OF,
    )

    assert len(candidates) == 2


async def test_customer_override_source_beats_price_list() -> None:
    override_id = uuid.uuid4()
    overrides = CustomerOverrideSource(
        FakeOverrideRepository(
            [
                make_candidate(
                    source_kind=PriceSourceKind.CUSTOMER_OVERRIDE,
                    source_id=override_id,
                    unit_price="1.8000",
                )
            ]
        )
    )
    price_lists = PriceListSource(FakeRepository([make_candidate(unit_price="2.0000")]))
    resolver = PriceResolver([overrides, price_lists])

    selection = await resolver.resolve(
        tenant_id=TENANT_ID,
        customer_id=CUSTOMER_ID,
        product_id=PRODUCT_ID,
        quantity=Decimal("10"),
        currency="USD",
        as_of=AS_OF,
    )

    assert selection.unit_price == Decimal("1.8000")
    assert selection.source.kind == PriceSourceKind.CUSTOMER_OVERRIDE
    assert selection.source.source_id == override_id


async def test_anonymous_quote_skips_customer_override_source() -> None:
    overrides = CustomerOverrideSource(
        FakeOverrideRepository(
            [make_candidate(source_kind=PriceSourceKind.CUSTOMER_OVERRIDE, unit_price="1.8000")]
        )
    )
    price_lists = PriceListSource(FakeRepository([make_candidate(unit_price="2.0000")]))
    resolver = PriceResolver([overrides, price_lists])

    selection = await resolver.resolve(
        tenant_id=TENANT_ID,
        customer_id=None,
        product_id=PRODUCT_ID,
        quantity=Decimal("10"),
        currency="USD",
        as_of=AS_OF,
    )

    assert selection.unit_price == Decimal("2.0000")
    assert selection.source.kind == PriceSourceKind.PRICE_LIST


async def test_price_list_source_filters_by_currency() -> None:
    repository = FakeRepository(
        [
            make_candidate(currency="USD", unit_price="2.0000"),
            make_candidate(currency="EUR", unit_price="1.8000"),
        ]
    )
    source = PriceListSource(repository)

    candidates = await source.candidates(
        tenant_id=TENANT_ID,
        customer_id=None,
        product_id=PRODUCT_ID,
        currency="eur",
        as_of=AS_OF,
    )

    assert [c.currency for c in candidates] == ["EUR"]


async def test_price_list_source_reports_currency_mismatch() -> None:
    source = PriceListSource(FakeRepository([make_candidate(currency="USD")]))

    with pytest.raises(PricingError) as exc_info:
        await source.candidates(
            tenant_id=TENANT_ID,
            customer_id=None,
            product_id=PRODUCT_ID,
            currency="EUR",
            as_of=AS_OF,
        )

    assert exc_info.value.code == PricingErrorCode.CURRENCY_MISMATCH


async def test_price_list_source_rejects_multiple_active_lists() -> None:
    source = PriceListSource(
        FakeRepository(
            [
                make_candidate(source_id=uuid.uuid4()),
                make_candidate(source_id=uuid.uuid4()),
            ]
        )
    )

    with pytest.raises(PricingError) as exc_info:
        await source.candidates(
            tenant_id=TENANT_ID,
            customer_id=None,
            product_id=PRODUCT_ID,
            currency="USD",
            as_of=AS_OF,
        )

    assert exc_info.value.code == PricingErrorCode.PRICE_LIST_AMBIGUOUS


async def test_price_list_source_ignores_expired_lists_for_ambiguity() -> None:
    source = PriceListSource(
        FakeRepository(
            [
                make_candidate(source_id=uuid.uuid4()),
                make_candidate(source_id=uuid.uuid4(), valid_to=date(2026, 10, 31)),
            ]
        )
    )

    candidates = await source.candidates(
        tenant_id=TENANT_ID,
        customer_id=None,
        product_id=PRODUCT_ID,
        currency="USD",
        as_of=AS_OF,
    )

    assert len(candidates) == 2


async def test_currency_mismatch_falls_back_to_lower_priority_source() -> None:
    repository = FakeRepository([make_candidate(currency="USD")])
    price_lists = PriceListSource(repository)
    override = FakeSource(
        "customer_override", candidates=[make_candidate(currency="EUR", unit_price="1.8000")]
    )

    resolver = PriceResolver([override, price_lists])
    selection = await resolver.resolve(
        tenant_id=TENANT_ID,
        customer_id=CUSTOMER_ID,
        product_id=PRODUCT_ID,
        quantity=Decimal("10"),
        currency="EUR",
        as_of=AS_OF,
    )

    assert selection.currency == "EUR"
    assert selection.unit_price == Decimal("1.8000")
