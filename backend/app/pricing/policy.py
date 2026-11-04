import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tenant import set_tenant_context
from app.models.pricing import PricingPolicy
from app.pricing.engine import (
    LineCalculation,
    PricingError,
    PricingErrorCode,
    PricingWarningCode,
    RoundingPolicy,
)


class PricingRoundingMode(StrEnum):
    ROUND_HALF_UP = "ROUND_HALF_UP"
    ROUND_HALF_EVEN = "ROUND_HALF_EVEN"
    ROUND_DOWN = "ROUND_DOWN"
    ROUND_UP = "ROUND_UP"


class MoqEnforcement(StrEnum):
    WARN = "WARN"
    BLOCK = "BLOCK"


DEFAULT_ROUNDING_MODE = PricingRoundingMode.ROUND_HALF_UP
DEFAULT_MOQ_ENFORCEMENT = MoqEnforcement.WARN
DEFAULT_MAX_DISCOUNT_PERCENT = Decimal("100.00")
_DISCOUNT_PERCENT_QUANTUM = Decimal("0.0001")


@dataclass(frozen=True)
class EffectivePricingPolicy:
    rounding_mode: str = DEFAULT_ROUNDING_MODE.value
    rounding_decimal_places: int | None = None
    moq_enforcement: str = DEFAULT_MOQ_ENFORCEMENT.value
    max_discount_percent: Decimal = DEFAULT_MAX_DISCOUNT_PERCENT

    @property
    def rounding(self) -> RoundingPolicy:
        return RoundingPolicy(
            decimal_places=self.rounding_decimal_places,
            rounding=self.rounding_mode,
        )

    def snapshot(self) -> dict[str, str | int | None]:
        return {
            "rounding_mode": self.rounding_mode,
            "rounding_decimal_places": self.rounding_decimal_places,
            "moq_enforcement": self.moq_enforcement,
            "max_discount_percent": str(self.max_discount_percent),
        }

    def discount_exceeds_limit(self, subtotal: Decimal, discount: Decimal) -> bool:
        return discount_percent(subtotal, discount) > self.max_discount_percent


def discount_percent(subtotal: Decimal, discount: Decimal) -> Decimal:
    if subtotal <= 0:
        return Decimal("0")
    return (discount / subtotal * Decimal("100")).quantize(_DISCOUNT_PERCENT_QUANTUM)


def enforce_moq_policy(
    lines: Sequence[LineCalculation],
    policy: EffectivePricingPolicy,
) -> None:
    if policy.moq_enforcement != MoqEnforcement.BLOCK.value:
        return
    for line in lines:
        if any(warning.code is PricingWarningCode.BELOW_MOQ for warning in line.warnings):
            raise PricingError(
                PricingErrorCode.MOQ_NOT_MET,
                f"quantity for product {line.product_id} is below the minimum order quantity",
            )


def effective_policy(row: PricingPolicy | None) -> EffectivePricingPolicy:
    if row is None:
        return EffectivePricingPolicy()
    return EffectivePricingPolicy(
        rounding_mode=row.rounding_mode,
        rounding_decimal_places=row.rounding_decimal_places,
        moq_enforcement=row.moq_enforcement,
        max_discount_percent=row.max_discount_percent,
    )


class PricingPolicyService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tenant_id: uuid.UUID) -> PricingPolicy | None:
        await set_tenant_context(self._session, tenant_id)
        return await self._session.scalar(
            select(PricingPolicy).where(PricingPolicy.tenant_id == tenant_id)
        )

    async def effective(self, tenant_id: uuid.UUID) -> EffectivePricingPolicy:
        return effective_policy(await self.get(tenant_id))

    async def upsert(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_id: uuid.UUID,
        rounding_mode: str,
        rounding_decimal_places: int | None,
        moq_enforcement: str,
        max_discount_percent: Decimal,
    ) -> tuple[PricingPolicy, list[str]]:
        await set_tenant_context(self._session, tenant_id)
        row = await self._session.scalar(
            select(PricingPolicy).where(PricingPolicy.tenant_id == tenant_id).with_for_update()
        )
        values = {
            "rounding_mode": rounding_mode,
            "rounding_decimal_places": rounding_decimal_places,
            "moq_enforcement": moq_enforcement,
            "max_discount_percent": max_discount_percent,
        }
        if row is None:
            row = PricingPolicy(tenant_id=tenant_id, updated_by_id=actor_id, **values)
            self._session.add(row)
            await self._session.flush()
            return row, list(values)

        changed = [field for field, value in values.items() if getattr(row, field) != value]
        if changed:
            for field in changed:
                setattr(row, field, values[field])
            row.updated_by_id = actor_id
            await self._session.flush()
        return row, changed
