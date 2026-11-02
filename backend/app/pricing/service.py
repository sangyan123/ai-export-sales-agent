import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tenant import set_tenant_context
from app.pricing.engine import (
    LineCalculation,
    PriceCandidate,
    PriceSelection,
    PricingError,
    PricingErrorCode,
    RoundingPolicy,
    UnitConversion,
    calculate_line,
    resolve_price,
)
from app.pricing.repository import PriceRepository


class PriceSourceProvider(Protocol):
    name: str

    async def candidates(
        self,
        *,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID | None,
        product_id: uuid.UUID,
        currency: str,
        as_of: date,
    ) -> Sequence[PriceCandidate]: ...


_FALLBACK_ERROR_CODES = frozenset(
    {
        PricingErrorCode.PRICE_MISSING,
        PricingErrorCode.PRICE_LIST_INACTIVE,
        PricingErrorCode.PRICE_EXPIRED,
        PricingErrorCode.PRICE_NOT_YET_VALID,
        PricingErrorCode.CURRENCY_MISMATCH,
        PricingErrorCode.NO_ELIGIBLE_TIER,
    }
)


class CustomerOverrideSource:
    name = "customer_override"

    def __init__(self, repository: PriceRepository) -> None:
        self._repository = repository

    async def candidates(
        self,
        *,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID | None,
        product_id: uuid.UUID,
        currency: str,
        as_of: date,
    ) -> Sequence[PriceCandidate]:
        if customer_id is None:
            return ()
        candidates = await self._repository.list_customer_override_candidates(
            tenant_id=tenant_id,
            customer_id=customer_id,
            product_id=product_id,
        )
        target = currency.strip().upper()
        matching = [c for c in candidates if c.currency.upper() == target]
        if not matching and candidates:
            raise PricingError(
                PricingErrorCode.CURRENCY_MISMATCH,
                f"no customer override found in {target}",
            )

        usable = [c for c in matching if _within(as_of, c.source_valid_from, c.source_valid_to)]
        if len(usable) > 1:
            raise PricingError(
                PricingErrorCode.CUSTOMER_PRICE_AMBIGUOUS,
                "more than one approved customer override is valid",
            )
        return matching


class PriceListSource:
    name = "price_list"

    def __init__(self, repository: PriceRepository) -> None:
        self._repository = repository

    async def candidates(
        self,
        *,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID | None,
        product_id: uuid.UUID,
        currency: str,
        as_of: date,
    ) -> Sequence[PriceCandidate]:
        candidates = await self._repository.list_price_tier_candidates(
            tenant_id=tenant_id, product_id=product_id
        )
        target = currency.strip().upper()
        matching = [c for c in candidates if c.currency.upper() == target]
        if not matching and candidates:
            raise PricingError(
                PricingErrorCode.CURRENCY_MISMATCH,
                f"no price list found in {target}",
            )

        active_valid_lists = {
            c.source_id
            for c in matching
            if c.source_status.strip().upper() == "ACTIVE"
            and _within(as_of, c.source_valid_from, c.source_valid_to)
        }
        if len(active_valid_lists) > 1:
            raise PricingError(
                PricingErrorCode.PRICE_LIST_AMBIGUOUS,
                "more than one active price list matches the product and currency",
            )
        return matching


class PriceResolver:
    """Try price sources in priority order and return the first valid price."""

    def __init__(self, providers: Sequence[PriceSourceProvider]) -> None:
        if not providers:
            raise ValueError("at least one price source provider is required")
        self._providers = tuple(providers)

    async def resolve(
        self,
        *,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID | None,
        product_id: uuid.UUID,
        quantity: Decimal,
        currency: str,
        as_of: date,
    ) -> PriceSelection:
        attempts: list[str] = []
        last_error: PricingError | None = None

        for provider in self._providers:
            try:
                candidates = await provider.candidates(
                    tenant_id=tenant_id,
                    customer_id=customer_id,
                    product_id=product_id,
                    currency=currency,
                    as_of=as_of,
                )
                return resolve_price(
                    candidates,
                    quantity=quantity,
                    as_of=as_of,
                    currency=currency,
                )
            except PricingError as error:
                if error.code not in _FALLBACK_ERROR_CODES:
                    raise
                attempts.append(f"{provider.name}:{error.code}")
                last_error = error

        if last_error is None:
            raise PricingError(PricingErrorCode.PRICE_MISSING, "no price sources configured")
        raise PricingError(
            last_error.code,
            f"{last_error.message} (tried {', '.join(attempts)})",
        ) from last_error


class PricingService:
    def __init__(
        self,
        session: AsyncSession,
        repository: PriceRepository,
        resolver: PriceResolver,
    ) -> None:
        self._session = session
        self._repository = repository
        self._resolver = resolver

    @classmethod
    def with_default_sources(cls, session: AsyncSession) -> "PricingService":
        repository = PriceRepository(session)
        return cls(
            session,
            repository,
            PriceResolver(
                [
                    CustomerOverrideSource(repository),
                    PriceListSource(repository),
                ]
            ),
        )

    async def calculate_line(
        self,
        *,
        tenant_id: uuid.UUID,
        product_id: uuid.UUID,
        quantity: Decimal,
        unit: str,
        currency: str,
        as_of: date,
        customer_id: uuid.UUID | None = None,
        conversions: Sequence[UnitConversion] = (),
        policy: RoundingPolicy | None = None,
    ) -> LineCalculation:
        await set_tenant_context(self._session, tenant_id)
        product = await self._repository.get_product(tenant_id=tenant_id, product_id=product_id)
        selection = await self._resolver.resolve(
            tenant_id=tenant_id,
            customer_id=customer_id,
            product_id=product_id,
            quantity=quantity,
            currency=currency,
            as_of=as_of,
        )
        return calculate_line(
            selection,
            quantity=quantity,
            unit=unit,
            conversions=conversions,
            moq=product.moq,
            moq_unit=product.sales_unit,
            policy=policy,
        )


def _within(value: date, start: date | None, end: date | None) -> bool:
    if start is not None and value < start:
        return False
    return not (end is not None and value > end)
