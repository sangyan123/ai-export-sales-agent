import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import CustomerPriceOverride
from app.models.pricing import PriceList, PriceTier
from app.models.product import Product
from app.pricing.engine import (
    PriceCandidate,
    PriceSourceKind,
    PricingError,
    PricingErrorCode,
)


class PriceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_product(self, *, tenant_id: uuid.UUID, product_id: uuid.UUID) -> Product:
        product = await self._session.scalar(
            select(Product).where(
                Product.tenant_id == tenant_id,
                Product.id == product_id,
            )
        )
        if product is None:
            raise PricingError(PricingErrorCode.PRODUCT_NOT_FOUND, "product not found for tenant")
        if product.status != "ACTIVE":
            raise PricingError(PricingErrorCode.PRODUCT_INACTIVE, "product is not active")
        return product

    async def list_price_tier_candidates(
        self, *, tenant_id: uuid.UUID, product_id: uuid.UUID
    ) -> Sequence[PriceCandidate]:
        """Load tiers joined with their price list.

        Validity and status are intentionally left to the pricing engine so it
        can report expired/not-yet-valid/inactive reasons precisely.
        """
        rows = (
            await self._session.execute(
                select(PriceTier, PriceList)
                .join(
                    PriceList,
                    (PriceTier.tenant_id == PriceList.tenant_id)
                    & (PriceTier.price_list_id == PriceList.id),
                )
                .where(
                    PriceTier.tenant_id == tenant_id,
                    PriceTier.product_id == product_id,
                )
                .order_by(PriceTier.min_quantity)
            )
        ).all()

        return [
            PriceCandidate(
                product_id=tier.product_id,
                currency=price_list.currency,
                min_quantity=tier.min_quantity,
                max_quantity=tier.max_quantity,
                unit_price=tier.unit_price,
                price_basis=tier.price_basis,
                unit=tier.unit,
                source_kind=PriceSourceKind.PRICE_LIST,
                source_id=price_list.id,
                source_status=price_list.status,
                source_valid_from=price_list.valid_from,
                source_valid_to=price_list.valid_to,
                source_version=price_list.version,
                source_detail_id=tier.id,
                tier_valid_from=tier.valid_from,
                tier_valid_to=tier.valid_to,
            )
            for tier, price_list in rows
        ]

    async def list_customer_override_candidates(
        self, *, tenant_id: uuid.UUID, customer_id: uuid.UUID, product_id: uuid.UUID
    ) -> Sequence[PriceCandidate]:
        """Load approved customer prices; validity is checked by the engine."""
        overrides = (
            await self._session.scalars(
                select(CustomerPriceOverride)
                .where(
                    CustomerPriceOverride.tenant_id == tenant_id,
                    CustomerPriceOverride.customer_id == customer_id,
                    CustomerPriceOverride.product_id == product_id,
                    CustomerPriceOverride.approval_status == "APPROVED",
                )
                .order_by(CustomerPriceOverride.valid_from)
            )
        ).all()

        return [
            PriceCandidate(
                product_id=override.product_id,
                currency=override.currency,
                min_quantity=Decimal("0"),
                max_quantity=None,
                unit_price=override.unit_price,
                price_basis=override.price_basis,
                unit=override.unit,
                source_kind=PriceSourceKind.CUSTOMER_OVERRIDE,
                source_id=override.id,
                source_status="ACTIVE",
                source_valid_from=override.valid_from,
                source_valid_to=override.valid_to,
            )
            for override in overrides
        ]
