import os
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.tenant import set_tenant_context
from app.models.pricing import PriceList, PriceTier
from app.models.product import Product
from app.models.tenant import Tenant
from app.pricing import (
    PriceRepository,
    PricingError,
    PricingErrorCode,
    PricingService,
    PricingWarningCode,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to run database integration tests",
)

AS_OF = date(2026, 11, 1)


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


async def seed_priced_product(
    session: AsyncSession,
    *,
    slug: str,
    moq: str = "1000",
    valid_to: date | None = None,
) -> tuple[Tenant, Product, PriceList, tuple[PriceTier, ...]]:
    tenant = Tenant(name=slug, slug=slug)
    session.add(tenant)
    await session.flush()
    await set_tenant_context(session, tenant.id)

    product = Product(
        tenant_id=tenant.id,
        product_code="BOLT-M8-30",
        product_name="Hex bolt M8x30 SS304",
        category="BOLT",
        sales_unit="PCS",
        moq=Decimal(moq),
    )
    price_list = PriceList(
        tenant_id=tenant.id,
        name="2026 USD",
        currency="USD",
        valid_from=date(2026, 1, 1),
        valid_to=valid_to,
        status="ACTIVE",
        version=1,
    )
    session.add_all([product, price_list])
    await session.flush()

    tiers = (
        PriceTier(
            tenant_id=tenant.id,
            price_list_id=price_list.id,
            product_id=product.id,
            min_quantity=Decimal("1"),
            max_quantity=Decimal("999"),
            unit_price=Decimal("2.5000"),
            price_basis="PER_PIECE",
            unit="PCS",
        ),
        PriceTier(
            tenant_id=tenant.id,
            price_list_id=price_list.id,
            product_id=product.id,
            min_quantity=Decimal("1000"),
            unit_price=Decimal("2.2000"),
            price_basis="PER_PIECE",
            unit="PCS",
        ),
    )
    session.add_all(tiers)
    await session.flush()
    return tenant, product, price_list, tiers


async def calculate(
    session: AsyncSession,
    tenant: Tenant,
    product: Product,
    *,
    quantity: str,
    unit: str = "PCS",
):
    service = PricingService.with_price_lists(session)
    return await service.calculate_line(
        tenant_id=tenant.id,
        product_id=product.id,
        quantity=Decimal(quantity),
        unit=unit,
        currency="USD",
        as_of=AS_OF,
    )


async def test_service_selects_tier_from_database(session: AsyncSession) -> None:
    tenant, product, _, tiers = await seed_priced_product(session, slug="tier-select")

    line = await calculate(session, tenant, product, quantity="1000")

    assert line.unit_price == Decimal("2.2000")
    assert line.line_total == Decimal("2200.0000")
    assert line.source.price_tier_id == tiers[1].id
    assert line.warnings == ()


async def test_service_flags_quantity_below_product_moq(session: AsyncSession) -> None:
    tenant, product, _, tiers = await seed_priced_product(session, slug="moq-warning")

    line = await calculate(session, tenant, product, quantity="500")

    assert line.source.price_tier_id == tiers[0].id
    assert line.unit_price == Decimal("2.5000")
    assert [w.code for w in line.warnings] == [PricingWarningCode.BELOW_MOQ]


async def test_expired_price_list_is_not_used(session: AsyncSession) -> None:
    tenant, product, _, _ = await seed_priced_product(
        session, slug="expired", valid_to=date(2026, 10, 31)
    )

    with pytest.raises(PricingError) as exc_info:
        await calculate(session, tenant, product, quantity="100")

    assert exc_info.value.code == PricingErrorCode.PRICE_EXPIRED


async def test_product_from_another_tenant_is_not_visible(session: AsyncSession) -> None:
    tenant_a, product_a, _, _ = await seed_priced_product(session, slug="tenant-a")
    tenant_b, _, _, _ = await seed_priced_product(session, slug="tenant-b")

    with pytest.raises(PricingError) as exc_info:
        await calculate(session, tenant_b, product_a, quantity="100")

    assert exc_info.value.code == PricingErrorCode.PRODUCT_NOT_FOUND


async def test_price_candidates_are_scoped_to_requested_tenant(
    session: AsyncSession,
) -> None:
    tenant_a, product_a, _, tiers_a = await seed_priced_product(session, slug="scope-a")
    _, _, _, _ = await seed_priced_product(session, slug="scope-b")
    repository = PriceRepository(session)

    candidates = await repository.list_price_tier_candidates(
        tenant_id=tenant_a.id, product_id=product_a.id
    )

    assert {c.price_tier_id for c in candidates} == {tier.id for tier in tiers_a}


async def test_inactive_product_is_rejected(session: AsyncSession) -> None:
    tenant, product, _, _ = await seed_priced_product(session, slug="inactive")
    product.status = "INACTIVE"
    await session.flush()

    with pytest.raises(PricingError) as exc_info:
        await calculate(session, tenant, product, quantity="100")

    assert exc_info.value.code == PricingErrorCode.PRODUCT_INACTIVE
