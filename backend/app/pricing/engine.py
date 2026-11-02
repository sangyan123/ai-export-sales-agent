import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP, Decimal
from enum import StrEnum


class PricingErrorCode(StrEnum):
    QUANTITY_INVALID = "QUANTITY_INVALID"
    UNIT_PRICE_INVALID = "UNIT_PRICE_INVALID"
    TIER_INVALID = "TIER_INVALID"
    PRICE_MISSING = "PRICE_MISSING"
    PRICE_LIST_INACTIVE = "PRICE_LIST_INACTIVE"
    PRICE_EXPIRED = "PRICE_EXPIRED"
    PRICE_NOT_YET_VALID = "PRICE_NOT_YET_VALID"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    UNIT_MISMATCH = "UNIT_MISMATCH"
    UNIT_CONVERSION_MISSING = "UNIT_CONVERSION_MISSING"
    UNIT_CONVERSION_INVALID = "UNIT_CONVERSION_INVALID"
    TIER_AMBIGUOUS = "TIER_AMBIGUOUS"
    NO_ELIGIBLE_TIER = "NO_ELIGIBLE_TIER"
    QUOTE_EMPTY = "QUOTE_EMPTY"
    DISCOUNT_INVALID = "DISCOUNT_INVALID"
    CHARGE_INVALID = "CHARGE_INVALID"


class PricingWarningCode(StrEnum):
    BELOW_MOQ = "BELOW_MOQ"


class PricingError(Exception):
    def __init__(self, code: PricingErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PricingWarning:
    code: PricingWarningCode
    message: str


@dataclass(frozen=True)
class PriceCandidate:
    price_tier_id: uuid.UUID
    product_id: uuid.UUID
    price_list_id: uuid.UUID
    currency: str
    min_quantity: Decimal
    max_quantity: Decimal | None
    unit_price: Decimal
    price_basis: str
    unit: str
    price_list_status: str
    price_list_valid_from: date
    price_list_valid_to: date | None
    price_list_version: int
    tier_valid_from: date | None = None
    tier_valid_to: date | None = None


@dataclass(frozen=True)
class PriceSource:
    price_list_id: uuid.UUID
    price_tier_id: uuid.UUID
    price_list_version: int
    price_list_valid_from: date
    price_list_valid_to: date | None
    tier_valid_from: date | None
    tier_valid_to: date | None


@dataclass(frozen=True)
class PriceSelection:
    product_id: uuid.UUID
    currency: str
    unit_price: Decimal
    price_basis: str
    price_unit: str
    source: PriceSource


@dataclass(frozen=True)
class UnitConversion:
    from_unit: str
    to_unit: str
    factor: Decimal


SUPPORTED_ROUNDING_MODES = {ROUND_HALF_UP, ROUND_HALF_EVEN, ROUND_DOWN, ROUND_UP}

CURRENCY_DECIMALS = {
    "BHD": 3,
    "CLP": 0,
    "ISK": 0,
    "JOD": 3,
    "JPY": 0,
    "KRW": 0,
    "KWD": 3,
    "LYD": 3,
    "OMR": 3,
    "TND": 3,
    "VND": 0,
}


@dataclass(frozen=True)
class RoundingPolicy:
    decimal_places: int | None = None
    rounding: str = ROUND_HALF_UP

    def __post_init__(self) -> None:
        if self.decimal_places is not None and self.decimal_places < 0:
            raise ValueError("decimal_places must be >= 0")
        if self.rounding not in SUPPORTED_ROUNDING_MODES:
            raise ValueError(f"unsupported rounding mode: {self.rounding}")


@dataclass(frozen=True)
class LineCalculation:
    currency: str
    requested_quantity: Decimal
    requested_unit: str
    priced_quantity: Decimal
    price_basis: str
    price_unit: str
    unit_price: Decimal
    unit_price_display: Decimal
    line_total: Decimal
    line_total_display: Decimal
    source: PriceSource
    warnings: tuple[PricingWarning, ...] = ()


@dataclass(frozen=True)
class QuoteCalculation:
    currency: str
    subtotal: Decimal
    subtotal_display: Decimal
    discount_total: Decimal
    discount_total_display: Decimal
    freight_total: Decimal
    freight_total_display: Decimal
    other_charges: Decimal
    other_charges_display: Decimal
    grand_total: Decimal
    grand_total_display: Decimal
    lines: tuple[LineCalculation, ...]


def quantize_money(amount: Decimal, currency: str, policy: RoundingPolicy | None = None) -> Decimal:
    policy = policy or RoundingPolicy()
    decimals = policy.decimal_places
    if decimals is None:
        decimals = CURRENCY_DECIMALS.get(currency.upper(), 2)
    quantum = Decimal(1).scaleb(-decimals)
    return amount.quantize(quantum, rounding=policy.rounding)


def resolve_price(
    candidates: Sequence[PriceCandidate],
    *,
    quantity: Decimal,
    as_of: date,
    currency: str | None = None,
) -> PriceSelection:
    """Pick the single valid tier for a quantity.

    Candidates must come from one already-selected price source (customer
    override, contract or price list); this function does not implement the
    source priority order.
    """
    quantity = _checked_decimal(quantity, "quantity")
    if quantity <= 0:
        raise PricingError(PricingErrorCode.QUANTITY_INVALID, "quantity must be positive")
    if not candidates:
        raise PricingError(PricingErrorCode.PRICE_MISSING, "no price candidates")

    eligible: list[PriceCandidate] = []
    inactive = expired = future = False
    for candidate in candidates:
        _validate_candidate(candidate)
        if candidate.price_list_status.strip().upper() != "ACTIVE":
            inactive = True
            continue
        if not _within(as_of, candidate.price_list_valid_from, candidate.price_list_valid_to):
            if candidate.price_list_valid_to is not None and as_of > candidate.price_list_valid_to:
                expired = True
            else:
                future = True
            continue
        if not _within(as_of, candidate.tier_valid_from, candidate.tier_valid_to):
            if candidate.tier_valid_to is not None and as_of > candidate.tier_valid_to:
                expired = True
            else:
                future = True
            continue
        eligible.append(candidate)

    if not eligible:
        if expired:
            raise PricingError(PricingErrorCode.PRICE_EXPIRED, "price is expired")
        if future:
            raise PricingError(PricingErrorCode.PRICE_NOT_YET_VALID, "price is not yet valid")
        if inactive:
            raise PricingError(PricingErrorCode.PRICE_LIST_INACTIVE, "price list is not active")
        raise PricingError(PricingErrorCode.PRICE_MISSING, "no usable price")

    if currency is not None:
        eligible = [c for c in eligible if c.currency.upper() == currency.upper()]
        if not eligible:
            raise PricingError(
                PricingErrorCode.CURRENCY_MISMATCH,
                f"no price available in {currency.upper()}",
            )

    currencies = {c.currency.upper() for c in eligible}
    if len(currencies) > 1:
        raise PricingError(
            PricingErrorCode.CURRENCY_MISMATCH,
            "candidates contain more than one currency",
        )

    _ensure_no_overlap(eligible)

    matches = [
        c
        for c in eligible
        if c.min_quantity <= quantity and (c.max_quantity is None or quantity <= c.max_quantity)
    ]
    if not matches:
        raise PricingError(
            PricingErrorCode.NO_ELIGIBLE_TIER,
            "quantity does not fall into any configured tier",
        )
    selected = max(matches, key=lambda c: c.min_quantity)

    return PriceSelection(
        product_id=selected.product_id,
        currency=selected.currency.upper(),
        unit_price=selected.unit_price,
        price_basis=selected.price_basis,
        price_unit=selected.unit,
        source=PriceSource(
            price_list_id=selected.price_list_id,
            price_tier_id=selected.price_tier_id,
            price_list_version=selected.price_list_version,
            price_list_valid_from=selected.price_list_valid_from,
            price_list_valid_to=selected.price_list_valid_to,
            tier_valid_from=selected.tier_valid_from,
            tier_valid_to=selected.tier_valid_to,
        ),
    )


def calculate_line(
    selection: PriceSelection,
    *,
    quantity: Decimal,
    unit: str,
    conversions: Sequence[UnitConversion] = (),
    moq: Decimal | None = None,
    moq_unit: str | None = None,
    policy: RoundingPolicy | None = None,
) -> LineCalculation:
    policy = policy or RoundingPolicy()
    quantity = _checked_decimal(quantity, "quantity")
    if quantity <= 0:
        raise PricingError(PricingErrorCode.QUANTITY_INVALID, "quantity must be positive")
    unit_price = _checked_decimal(selection.unit_price, "unit_price")
    if unit_price < 0:
        raise PricingError(PricingErrorCode.UNIT_PRICE_INVALID, "unit price must not be negative")

    requested_unit = _normalize_unit(unit)
    price_unit = _normalize_unit(selection.price_unit)
    factor = Decimal("1")
    if requested_unit != price_unit:
        factor = _find_conversion_factor(conversions, requested_unit, price_unit)

    priced_quantity = quantity * factor
    line_total = priced_quantity * unit_price

    warnings: list[PricingWarning] = []
    if moq is not None:
        moq = _checked_decimal(moq, "moq")
        if moq < 0:
            raise PricingError(PricingErrorCode.TIER_INVALID, "moq must not be negative")
        if moq_unit is not None and _normalize_unit(moq_unit) != requested_unit:
            raise PricingError(
                PricingErrorCode.UNIT_MISMATCH,
                "moq unit does not match requested unit",
            )
        if quantity < moq:
            warnings.append(
                PricingWarning(
                    PricingWarningCode.BELOW_MOQ,
                    f"quantity {quantity} is below MOQ {moq}",
                )
            )

    return LineCalculation(
        currency=selection.currency.upper(),
        requested_quantity=quantity,
        requested_unit=requested_unit,
        priced_quantity=priced_quantity,
        price_basis=selection.price_basis,
        price_unit=price_unit,
        unit_price=unit_price,
        unit_price_display=quantize_money(unit_price, selection.currency, policy),
        line_total=line_total,
        line_total_display=quantize_money(line_total, selection.currency, policy),
        source=selection.source,
        warnings=tuple(warnings),
    )


def calculate_quote(
    lines: Sequence[LineCalculation],
    *,
    discount_total: Decimal = Decimal("0"),
    freight_total: Decimal = Decimal("0"),
    other_charges: Decimal = Decimal("0"),
    policy: RoundingPolicy | None = None,
) -> QuoteCalculation:
    policy = policy or RoundingPolicy()
    if not lines:
        raise PricingError(PricingErrorCode.QUOTE_EMPTY, "quote must contain at least one line")

    currencies = {line.currency.upper() for line in lines}
    if len(currencies) > 1:
        raise PricingError(
            PricingErrorCode.CURRENCY_MISMATCH, "quote lines use different currencies"
        )
    currency = currencies.pop()

    discount_total = _checked_decimal(discount_total, "discount_total")
    freight_total = _checked_decimal(freight_total, "freight_total")
    other_charges = _checked_decimal(other_charges, "other_charges")

    subtotal = sum((line.line_total for line in lines), Decimal("0"))
    if discount_total < 0 or discount_total > subtotal:
        raise PricingError(
            PricingErrorCode.DISCOUNT_INVALID,
            "discount must be between zero and the subtotal",
        )
    if freight_total < 0 or other_charges < 0:
        raise PricingError(
            PricingErrorCode.CHARGE_INVALID, "freight and other charges must not be negative"
        )

    grand_total = subtotal - discount_total + freight_total + other_charges

    return QuoteCalculation(
        currency=currency,
        subtotal=subtotal,
        subtotal_display=quantize_money(subtotal, currency, policy),
        discount_total=discount_total,
        discount_total_display=quantize_money(discount_total, currency, policy),
        freight_total=freight_total,
        freight_total_display=quantize_money(freight_total, currency, policy),
        other_charges=other_charges,
        other_charges_display=quantize_money(other_charges, currency, policy),
        grand_total=grand_total,
        grand_total_display=quantize_money(grand_total, currency, policy),
        lines=tuple(lines),
    )


def _checked_decimal(value: Decimal, field: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field} must be Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise TypeError(f"{field} must be a finite Decimal")
    return value


def _normalize_unit(unit: str) -> str:
    normalized = unit.strip().upper()
    if not normalized:
        raise PricingError(PricingErrorCode.UNIT_MISMATCH, "unit must not be empty")
    return normalized


def _within(value: date, start: date | None, end: date | None) -> bool:
    if start is not None and value < start:
        return False
    return not (end is not None and value > end)


def _validate_candidate(candidate: PriceCandidate) -> None:
    min_quantity = _checked_decimal(candidate.min_quantity, "min_quantity")
    if min_quantity < 0:
        raise PricingError(PricingErrorCode.TIER_INVALID, "tier min_quantity must not be negative")
    if candidate.max_quantity is not None:
        max_quantity = _checked_decimal(candidate.max_quantity, "max_quantity")
        if max_quantity <= min_quantity:
            raise PricingError(
                PricingErrorCode.TIER_INVALID,
                "tier max_quantity must be greater than min_quantity",
            )
    unit_price = _checked_decimal(candidate.unit_price, "unit_price")
    if unit_price < 0:
        raise PricingError(PricingErrorCode.UNIT_PRICE_INVALID, "unit price must not be negative")


def _ensure_no_overlap(candidates: Sequence[PriceCandidate]) -> None:
    for index, left in enumerate(candidates):
        for right in candidates[index + 1 :]:
            if _intervals_overlap(left, right):
                raise PricingError(
                    PricingErrorCode.TIER_AMBIGUOUS,
                    "price tier quantity ranges overlap for the same price source",
                )


def _intervals_overlap(left: PriceCandidate, right: PriceCandidate) -> bool:
    left_end = left.max_quantity
    right_end = right.max_quantity
    left_before_right = left_end is None or right.min_quantity <= left_end
    right_before_left = right_end is None or left.min_quantity <= right_end
    return left_before_right and right_before_left


def _find_conversion_factor(
    conversions: Sequence[UnitConversion],
    from_unit: str,
    to_unit: str,
) -> Decimal:
    for conversion in conversions:
        if (
            _normalize_unit(conversion.from_unit) == from_unit
            and _normalize_unit(conversion.to_unit) == to_unit
        ):
            factor = _checked_decimal(conversion.factor, "conversion factor")
            if factor <= 0:
                raise PricingError(
                    PricingErrorCode.UNIT_CONVERSION_INVALID,
                    "unit conversion factor must be positive",
                )
            return factor
    raise PricingError(
        PricingErrorCode.UNIT_CONVERSION_MISSING,
        f"no explicit conversion from {from_unit} to {to_unit}",
    )
