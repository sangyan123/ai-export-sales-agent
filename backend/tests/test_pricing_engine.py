import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.pricing import (
    PriceCandidate,
    PriceSelection,
    PriceSourceKind,
    PricingError,
    PricingErrorCode,
    PricingWarningCode,
    RoundingPolicy,
    UnitConversion,
    calculate_line,
    calculate_quote,
    resolve_price,
)

AS_OF = date(2026, 11, 1)
PRODUCT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
PRICE_LIST_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def make_candidate(
    *,
    min_quantity: str = "1",
    max_quantity: str | None = None,
    unit_price: str = "1.0000",
    currency: str = "USD",
    unit: str = "PCS",
    price_basis: str = "PER_PIECE",
    status: str = "ACTIVE",
    valid_from: date = date(2026, 1, 1),
    valid_to: date | None = None,
    tier_valid_from: date | None = None,
    tier_valid_to: date | None = None,
) -> PriceCandidate:
    return PriceCandidate(
        product_id=PRODUCT_ID,
        currency=currency,
        min_quantity=Decimal(min_quantity),
        max_quantity=Decimal(max_quantity) if max_quantity is not None else None,
        unit_price=Decimal(unit_price),
        price_basis=price_basis,
        unit=unit,
        source_kind=PriceSourceKind.PRICE_LIST,
        source_id=PRICE_LIST_ID,
        source_status=status,
        source_valid_from=valid_from,
        source_valid_to=valid_to,
        source_version=3,
        source_detail_id=uuid.uuid4(),
        tier_valid_from=tier_valid_from,
        tier_valid_to=tier_valid_to,
    )


def select_one(quantity: str = "100", **kwargs: object) -> PriceSelection:
    return resolve_price(
        [make_candidate(**kwargs)],
        quantity=Decimal(quantity),
        as_of=AS_OF,
    )


def calculate_one(
    *,
    quantity: str = "100",
    unit: str = "PCS",
    unit_price: str = "2.5000",
    currency: str = "USD",
    price_unit: str = "PCS",
    price_basis: str = "PER_PIECE",
    conversions: tuple[UnitConversion, ...] = (),
    moq: str | None = None,
    moq_unit: str | None = None,
    policy: RoundingPolicy | None = None,
):
    selection = select_one(
        quantity=quantity,
        unit_price=unit_price,
        currency=currency,
        unit=price_unit,
        price_basis=price_basis,
    )
    return calculate_line(
        selection,
        quantity=Decimal(quantity),
        unit=unit,
        conversions=conversions,
        moq=Decimal(moq) if moq is not None else None,
        moq_unit=moq_unit,
        policy=policy,
    )


def assert_error(code: PricingErrorCode, func, *args: object, **kwargs: object) -> None:
    with pytest.raises(PricingError) as exc_info:
        func(*args, **kwargs)
    assert exc_info.value.code == code


def test_selects_tier_on_quantity_boundaries() -> None:
    tiers = [
        make_candidate(min_quantity="1", max_quantity="999", unit_price="2.5000"),
        make_candidate(min_quantity="1000", unit_price="2.0000"),
    ]

    low = resolve_price(tiers, quantity=Decimal("999"), as_of=AS_OF)
    high = resolve_price(tiers, quantity=Decimal("1000"), as_of=AS_OF)

    assert low.unit_price == Decimal("2.5000")
    assert high.unit_price == Decimal("2.0000")


def test_quantity_outside_all_tiers_is_not_priceable() -> None:
    assert_error(
        PricingErrorCode.NO_ELIGIBLE_TIER,
        resolve_price,
        [make_candidate(min_quantity="100")],
        quantity=Decimal("50"),
        as_of=AS_OF,
    )


def test_no_candidates_means_price_missing() -> None:
    assert_error(
        PricingErrorCode.PRICE_MISSING,
        resolve_price,
        [],
        quantity=Decimal("10"),
        as_of=AS_OF,
    )


def test_expired_price_list_is_rejected() -> None:
    assert_error(
        PricingErrorCode.PRICE_EXPIRED,
        resolve_price,
        [make_candidate(valid_to=date(2026, 10, 31))],
        quantity=Decimal("10"),
        as_of=AS_OF,
    )


def test_not_yet_valid_price_list_is_rejected() -> None:
    assert_error(
        PricingErrorCode.PRICE_NOT_YET_VALID,
        resolve_price,
        [make_candidate(valid_from=date(2026, 11, 2))],
        quantity=Decimal("10"),
        as_of=AS_OF,
    )


def test_inactive_price_list_is_rejected() -> None:
    assert_error(
        PricingErrorCode.PRICE_LIST_INACTIVE,
        resolve_price,
        [make_candidate(status="INACTIVE")],
        quantity=Decimal("10"),
        as_of=AS_OF,
    )


def test_expired_tier_is_rejected() -> None:
    assert_error(
        PricingErrorCode.PRICE_EXPIRED,
        resolve_price,
        [make_candidate(tier_valid_to=date(2026, 10, 31))],
        quantity=Decimal("10"),
        as_of=AS_OF,
    )


def test_overlapping_tiers_are_ambiguous() -> None:
    tiers = [
        make_candidate(min_quantity="1", max_quantity="1000", unit_price="2.0000"),
        make_candidate(min_quantity="500", max_quantity="2000", unit_price="1.8000"),
    ]
    assert_error(
        PricingErrorCode.TIER_AMBIGUOUS,
        resolve_price,
        tiers,
        quantity=Decimal("100"),
        as_of=AS_OF,
    )


def test_currency_filter_selects_matching_price() -> None:
    tiers = [
        make_candidate(currency="USD", unit_price="2.0000"),
        make_candidate(currency="EUR", unit_price="1.8000"),
    ]

    selected = resolve_price(tiers, quantity=Decimal("10"), as_of=AS_OF, currency="EUR")

    assert selected.currency == "EUR"
    assert selected.unit_price == Decimal("1.8000")


def test_mixed_currencies_without_filter_are_rejected() -> None:
    tiers = [
        make_candidate(currency="USD"),
        make_candidate(currency="EUR"),
    ]
    assert_error(
        PricingErrorCode.CURRENCY_MISMATCH,
        resolve_price,
        tiers,
        quantity=Decimal("10"),
        as_of=AS_OF,
    )


def test_invalid_quantity_range_is_rejected() -> None:
    assert_error(
        PricingErrorCode.TIER_INVALID,
        resolve_price,
        [make_candidate(min_quantity="100", max_quantity="100")],
        quantity=Decimal("100"),
        as_of=AS_OF,
    )


def test_negative_unit_price_is_rejected() -> None:
    assert_error(
        PricingErrorCode.UNIT_PRICE_INVALID,
        resolve_price,
        [make_candidate(unit_price="-1")],
        quantity=Decimal("10"),
        as_of=AS_OF,
    )


def test_line_with_same_unit_multiplies_quantity_by_price() -> None:
    line = calculate_one(quantity="5000", unit_price="0.2500")

    assert line.priced_quantity == Decimal("5000")
    assert line.line_total == Decimal("1250.0000")
    assert line.line_total_display == Decimal("1250.00")
    assert line.unit_price_display == Decimal("0.25")
    assert line.warnings == ()


def test_line_requires_explicit_unit_conversion() -> None:
    assert_error(
        PricingErrorCode.UNIT_CONVERSION_MISSING,
        calculate_one,
        quantity="5000",
        unit="PCS",
        unit_price="3.20",
        price_unit="KG",
        price_basis="PER_KG",
    )


def test_line_converts_units_with_declared_factor() -> None:
    line = calculate_one(
        quantity="5000",
        unit="PCS",
        unit_price="3.20",
        price_unit="KG",
        price_basis="PER_KG",
        conversions=(UnitConversion(from_unit="PCS", to_unit="KG", factor=Decimal("0.00025")),),
    )

    assert line.priced_quantity == Decimal("1.25000000")
    assert line.line_total == Decimal("4.0000000000")
    assert line.line_total_display == Decimal("4.00")


def test_non_positive_conversion_factor_is_rejected() -> None:
    assert_error(
        PricingErrorCode.UNIT_CONVERSION_INVALID,
        calculate_one,
        quantity="5000",
        unit="PCS",
        price_unit="KG",
        conversions=(UnitConversion(from_unit="PCS", to_unit="KG", factor=Decimal("0")),),
    )


def test_below_moq_is_flagged_but_calculated() -> None:
    line = calculate_one(quantity="500", moq="1000", moq_unit="PCS")

    assert line.line_total == Decimal("1250.0000")
    assert [warning.code for warning in line.warnings] == [PricingWarningCode.BELOW_MOQ]


def test_moq_unit_mismatch_is_rejected() -> None:
    assert_error(
        PricingErrorCode.UNIT_MISMATCH,
        calculate_one,
        quantity="500",
        moq="1000",
        moq_unit="KG",
    )


def test_rounding_uses_currency_precision_and_half_up() -> None:
    usd = calculate_one(quantity="1", unit_price="0.1250")
    jpy = calculate_one(quantity="1", unit_price="1234.5", currency="JPY")

    assert usd.line_total_display == Decimal("0.13")
    assert jpy.line_total_display == Decimal("1235")


def test_rounding_policy_can_override_decimal_places() -> None:
    line = calculate_one(
        quantity="1",
        unit_price="0.1250",
        policy=RoundingPolicy(decimal_places=4),
    )

    assert line.line_total_display == Decimal("0.1250")


def test_quote_totals_keep_raw_values_and_display_values() -> None:
    first = calculate_one(quantity="100", unit_price="2.5000")
    second = calculate_one(quantity="50", unit_price="3.0000")

    quote = calculate_quote(
        [first, second],
        discount_total=Decimal("25"),
        freight_total=Decimal("30"),
        other_charges=Decimal("5"),
    )

    assert quote.subtotal == Decimal("400.0000")
    assert quote.subtotal_display == Decimal("400.00")
    assert quote.grand_total == Decimal("410.0000")
    assert quote.grand_total_display == Decimal("410.00")


def test_quote_rejects_mixed_currencies() -> None:
    line = calculate_one()
    assert_error(
        PricingErrorCode.CURRENCY_MISMATCH,
        calculate_quote,
        [line, replace(line, currency="EUR")],
    )


def test_quote_rejects_discount_above_subtotal() -> None:
    line = calculate_one(quantity="100", unit_price="2.5000")
    assert_error(
        PricingErrorCode.DISCOUNT_INVALID,
        calculate_quote,
        [line],
        discount_total=Decimal("300"),
    )


def test_quote_rejects_negative_charges() -> None:
    line = calculate_one()
    assert_error(
        PricingErrorCode.CHARGE_INVALID,
        calculate_quote,
        [line],
        freight_total=Decimal("-1"),
    )


def test_empty_quote_is_rejected() -> None:
    assert_error(PricingErrorCode.QUOTE_EMPTY, calculate_quote, [])


def test_negative_quantity_is_rejected() -> None:
    assert_error(
        PricingErrorCode.QUANTITY_INVALID,
        resolve_price,
        [make_candidate()],
        quantity=Decimal("-1"),
        as_of=AS_OF,
    )


def test_float_input_is_rejected() -> None:
    with pytest.raises(TypeError, match="must be Decimal"):
        resolve_price(
            [make_candidate()],
            quantity=100.0,  # type: ignore[arg-type]
            as_of=AS_OF,
        )
