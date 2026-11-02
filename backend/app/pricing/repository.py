import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pricing import PriceList, PriceTier
from app.models.product import Product
from app.pricing.engine import PriceCandidate, PricingError, PricingErrorCode


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
                price_tier_id=tier.id,
                product_id=tier.product_id,
                price_list_id=price_list.id,
                currency=price_list.currency,
                min_quantity=tier.min_quantity,
                max_quantity=tier.max_quantity,
                unit_price=tier.unit_price,
                price_basis=tier.price_basis,
                unit=tier.unit,
                price_list_status=price_list.status,
                price_list_valid_from=price_list.valid_from,
                price_list_valid_to=price_list.valid_to,
                price_list_version=price_list.version,
                tier_valid_from=tier.valid_from,
                tier_valid_to=tier.valid_to,
            )
            for tier, price_list in rows
        ]
