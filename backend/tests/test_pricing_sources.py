import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

import pytest

from app.pricing import (
    PriceCandidate,
    PriceListSource,
    PriceResolver,
    PricingError,
    PricingErrorCode,
)

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-00000000000a")
PRODUCT_ID = uuid.UUID("00000000-0000-0000-0000-00000000000b")
AS_OF = date(2026, 11, 1)


def make_candidate(
    *,
    price_list_id: uuid.UUID | None = None,
    currency: str = "USD",
    min_quantity: str = "1",
    max_quantity: str | None = None,
    unit_price: str = "2.0000",
    status: str = "ACTIVE",
    valid_from: date = date(2026, 1, 1),
    valid_to: date | None = None,
) -> PriceCandidate:
    return PriceCandidate(
        price_tier_id=uuid.uuid4(),
        product_id=PRODUCT_ID,
        price_list_id=price_list_id or uuid.uuid4(),
        currency=currency,
        min_quantity=Decimal(min_quantity),
        max_quantity=Decimal(max_quantity) if max_quantity is not None else None,
        unit_price=Decimal(unit_price),
        price_basis="PER_PIECE",
        unit="PCS",
        price_list_status=status,
        price_list_valid_from=valid_from,
        price_list_valid_to=valid_to,
        price_list_version=1,
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


async def resolve_with(providers: Sequence[FakeSource], quantity: str = "10"):
    resolver = PriceResolver(providers)
    return await resolver.resolve(
        tenant_id=TENANT_ID,
        product_id=PRODUCT_ID,
        quantity=Decimal(quantity),
        currency="USD",
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
            product_id=PRODUCT_ID,
            currency="EUR",
            as_of=AS_OF,
        )

    assert exc_info.value.code == PricingErrorCode.CURRENCY_MISMATCH


async def test_price_list_source_rejects_multiple_active_lists() -> None:
    source = PriceListSource(
        FakeRepository(
            [
                make_candidate(price_list_id=uuid.uuid4()),
                make_candidate(price_list_id=uuid.uuid4()),
            ]
        )
    )

    with pytest.raises(PricingError) as exc_info:
        await source.candidates(
            tenant_id=TENANT_ID,
            product_id=PRODUCT_ID,
            currency="USD",
            as_of=AS_OF,
        )

    assert exc_info.value.code == PricingErrorCode.PRICE_LIST_AMBIGUOUS


async def test_price_list_source_ignores_expired_lists_for_ambiguity() -> None:
    source = PriceListSource(
        FakeRepository(
            [
                make_candidate(price_list_id=uuid.uuid4()),
                make_candidate(price_list_id=uuid.uuid4(), valid_to=date(2026, 10, 31)),
            ]
        )
    )

    candidates = await source.candidates(
        tenant_id=TENANT_ID,
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
        product_id=PRODUCT_ID,
        quantity=Decimal("10"),
        currency="EUR",
        as_of=AS_OF,
    )

    assert selection.currency == "EUR"
    assert selection.unit_price == Decimal("1.8000")
