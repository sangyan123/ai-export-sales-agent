import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import decimal_str, envelope, iso_datetime
from app.api.deps import RequestContext, SessionDep, require_permission
from app.api.enums import CatalogStatus, PriceBasis
from app.api.errors import ApiError
from app.core.permissions import Permission
from app.db.session import commit_or_rollback
from app.db.tenant import set_tenant_context
from app.models.pricing import PriceList, PriceTier
from app.models.product import Product

router = APIRouter(tags=["price-lists"])

PricingReadContext = Annotated[RequestContext, Depends(require_permission(Permission.PRICING_READ))]
PricingUpdateContext = Annotated[
    RequestContext, Depends(require_permission(Permission.PRICING_UPDATE))
]


class PriceTierCreate(BaseModel):
    product_id: uuid.UUID
    min_quantity: Decimal = Field(ge=0)
    max_quantity: Decimal | None = Field(default=None, gt=0)
    unit_price: Decimal = Field(ge=0)
    price_basis: PriceBasis
    unit: str = Field(min_length=1, max_length=20)
    valid_from: date | None = None
    valid_to: date | None = None

    @model_validator(mode="after")
    def validate_ranges(self) -> "PriceTierCreate":
        if self.max_quantity is not None and self.max_quantity <= self.min_quantity:
            raise ValueError("max_quantity must be greater than min_quantity")
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to must not be before valid_from")
        return self


class PriceTierUpdate(BaseModel):
    min_quantity: Decimal | None = Field(default=None, ge=0)
    max_quantity: Decimal | None = Field(default=None, gt=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    price_basis: PriceBasis | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    valid_from: date | None = None
    valid_to: date | None = None


class PriceListCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    valid_from: date
    valid_to: date | None = None
    status: CatalogStatus = CatalogStatus.ACTIVE
    version: int = Field(default=1, ge=1)
    tiers: list[PriceTierCreate] = Field(default_factory=list)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @model_validator(mode="after")
    def validate_validity(self) -> "PriceListCreate":
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to must not be before valid_from")
        return self


class PriceListUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    valid_to: date | None = None
    status: CatalogStatus | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


def _price_list_summary(price_list: PriceList) -> dict[str, Any]:
    return {
        "id": str(price_list.id),
        "name": price_list.name,
        "currency": price_list.currency,
        "valid_from": price_list.valid_from.isoformat(),
        "valid_to": price_list.valid_to.isoformat() if price_list.valid_to else None,
        "status": price_list.status,
        "version": price_list.version,
        "created_at": iso_datetime(price_list.created_at),
        "updated_at": iso_datetime(price_list.updated_at),
    }


def _price_tier_detail(tier: PriceTier) -> dict[str, Any]:
    return {
        "id": str(tier.id),
        "price_list_id": str(tier.price_list_id),
        "product_id": str(tier.product_id),
        "min_quantity": decimal_str(tier.min_quantity),
        "max_quantity": decimal_str(tier.max_quantity),
        "unit_price": decimal_str(tier.unit_price),
        "price_basis": tier.price_basis,
        "unit": tier.unit,
        "valid_from": tier.valid_from.isoformat() if tier.valid_from else None,
        "valid_to": tier.valid_to.isoformat() if tier.valid_to else None,
        "created_at": iso_datetime(tier.created_at),
        "updated_at": iso_datetime(tier.updated_at),
    }


def _price_list_detail(price_list: PriceList, tiers: list[PriceTier]) -> dict[str, Any]:
    return {
        **_price_list_summary(price_list),
        "tiers": [_price_tier_detail(tier) for tier in tiers],
    }


def _quantities_overlap(
    start_a: Decimal, end_a: Decimal | None, start_b: Decimal, end_b: Decimal | None
) -> bool:
    return (end_a is None or start_b <= end_a) and (end_b is None or start_a <= end_b)


def _dates_overlap(
    start_a: date | None, end_a: date | None, start_b: date | None, end_b: date | None
) -> bool:
    if start_a is not None and end_b is not None and start_a > end_b:
        return False
    if start_b is not None and end_a is not None and start_b > end_a:
        return False
    return True


def _validate_tier_ranges(
    min_quantity: Decimal,
    max_quantity: Decimal | None,
    valid_from: date | None,
    valid_to: date | None,
) -> None:
    if max_quantity is not None and max_quantity <= min_quantity:
        raise ApiError(
            400, "PRICE_TIER_RANGE_INVALID", "max_quantity must be greater than min_quantity"
        )
    if valid_from and valid_to and valid_to < valid_from:
        raise ApiError(400, "PRICE_TIER_RANGE_INVALID", "valid_to is before valid_from")


async def _ensure_product(
    session: AsyncSession, tenant_id: uuid.UUID, product_id: uuid.UUID
) -> None:
    exists = await session.scalar(
        select(Product.id).where(Product.tenant_id == tenant_id, Product.id == product_id)
    )
    if exists is None:
        raise ApiError(404, "PRODUCT_NOT_FOUND", "product not found")


async def _get_price_list(
    session: AsyncSession, tenant_id: uuid.UUID, price_list_id: uuid.UUID
) -> PriceList:
    await set_tenant_context(session, tenant_id)
    price_list = await session.scalar(
        select(PriceList).where(
            PriceList.tenant_id == tenant_id,
            PriceList.id == price_list_id,
        )
    )
    if price_list is None:
        raise ApiError(404, "PRICE_LIST_NOT_FOUND", "price list not found")
    return price_list


async def _get_tier(session: AsyncSession, tenant_id: uuid.UUID, tier_id: uuid.UUID) -> PriceTier:
    await set_tenant_context(session, tenant_id)
    tier = await session.scalar(
        select(PriceTier).where(PriceTier.tenant_id == tenant_id, PriceTier.id == tier_id)
    )
    if tier is None:
        raise ApiError(404, "PRICE_TIER_NOT_FOUND", "price tier not found")
    return tier


async def _load_price_list_detail(
    session: AsyncSession, tenant_id: uuid.UUID, price_list_id: uuid.UUID
) -> dict[str, Any]:
    price_list = await _get_price_list(session, tenant_id, price_list_id)
    tiers = list(
        await session.scalars(
            select(PriceTier)
            .where(
                PriceTier.tenant_id == tenant_id,
                PriceTier.price_list_id == price_list_id,
            )
            .order_by(PriceTier.product_id, PriceTier.min_quantity)
        )
    )
    return _price_list_detail(price_list, tiers)


async def _ensure_no_tier_overlap(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    price_list_id: uuid.UUID,
    product_id: uuid.UUID,
    min_quantity: Decimal,
    max_quantity: Decimal | None,
    valid_from: date | None,
    valid_to: date | None,
    exclude_tier_id: uuid.UUID | None = None,
) -> None:
    statement = select(PriceTier).where(
        PriceTier.tenant_id == tenant_id,
        PriceTier.price_list_id == price_list_id,
        PriceTier.product_id == product_id,
    )
    if exclude_tier_id is not None:
        statement = statement.where(PriceTier.id != exclude_tier_id)
    existing = list(await session.scalars(statement))
    for tier in existing:
        if _quantities_overlap(
            min_quantity, max_quantity, tier.min_quantity, tier.max_quantity
        ) and _dates_overlap(valid_from, valid_to, tier.valid_from, tier.valid_to):
            raise ApiError(
                409,
                "PRICE_TIER_OVERLAP",
                "price tier quantity range overlaps an existing tier for the same dates",
            )


@router.get("/price-lists")
async def list_price_lists(
    context: PricingReadContext,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    status_filter: Annotated[CatalogStatus | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    await set_tenant_context(session, context.tenant_id)
    conditions = [PriceList.tenant_id == context.tenant_id]
    if currency:
        conditions.append(PriceList.currency == currency.upper())
    if status_filter is not None:
        conditions.append(PriceList.status == status_filter.value)

    total = await session.scalar(select(func.count()).select_from(PriceList).where(*conditions))
    price_lists = list(
        await session.scalars(
            select(PriceList)
            .where(*conditions)
            .order_by(PriceList.valid_from.desc(), PriceList.name)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return envelope(
        [_price_list_summary(price_list) for price_list in price_lists],
        context,
        page=page,
        page_size=page_size,
        total=int(total or 0),
    )


@router.post("/price-lists", status_code=status.HTTP_201_CREATED)
async def create_price_list(
    payload: PriceListCreate,
    context: PricingUpdateContext,
    session: SessionDep,
) -> dict[str, Any]:
    await set_tenant_context(session, context.tenant_id)

    product_ids = {tier.product_id for tier in payload.tiers}
    if product_ids:
        found = set(
            await session.scalars(
                select(Product.id).where(
                    Product.tenant_id == context.tenant_id,
                    Product.id.in_(product_ids),
                )
            )
        )
        missing = product_ids - found
        if missing:
            raise ApiError(404, "PRODUCT_NOT_FOUND", "one or more products were not found")

    by_product: dict[uuid.UUID, list[PriceTierCreate]] = {}
    for tier in payload.tiers:
        by_product.setdefault(tier.product_id, []).append(tier)
    for tiers in by_product.values():
        for index, left in enumerate(tiers):
            for right in tiers[index + 1 :]:
                if _quantities_overlap(
                    left.min_quantity,
                    left.max_quantity,
                    right.min_quantity,
                    right.max_quantity,
                ) and _dates_overlap(
                    left.valid_from, left.valid_to, right.valid_from, right.valid_to
                ):
                    raise ApiError(
                        409,
                        "PRICE_TIER_OVERLAP",
                        "price tier quantity ranges overlap within the request",
                    )

    price_list = PriceList(
        tenant_id=context.tenant_id,
        name=payload.name,
        currency=payload.currency,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        status=payload.status.value,
        version=payload.version,
    )
    session.add(price_list)
    await session.flush()

    session.add_all(
        [
            PriceTier(
                tenant_id=context.tenant_id,
                price_list_id=price_list.id,
                product_id=tier.product_id,
                min_quantity=tier.min_quantity,
                max_quantity=tier.max_quantity,
                unit_price=tier.unit_price,
                price_basis=tier.price_basis.value,
                unit=tier.unit,
                valid_from=tier.valid_from,
                valid_to=tier.valid_to,
            )
            for tier in payload.tiers
        ]
    )
    await session.flush()
    await commit_or_rollback(session)
    return envelope(
        await _load_price_list_detail(session, context.tenant_id, price_list.id), context
    )


@router.get("/price-lists/{price_list_id}")
async def get_price_list(
    price_list_id: uuid.UUID,
    context: PricingReadContext,
    session: SessionDep,
) -> dict[str, Any]:
    return envelope(
        await _load_price_list_detail(session, context.tenant_id, price_list_id), context
    )


@router.patch("/price-lists/{price_list_id}")
async def update_price_list(
    price_list_id: uuid.UUID,
    payload: PriceListUpdate,
    context: PricingUpdateContext,
    session: SessionDep,
) -> dict[str, Any]:
    price_list = await _get_price_list(session, context.tenant_id, price_list_id)
    data = payload.model_dump(exclude_unset=True, exclude_none=True)

    if "valid_to" in data and data["valid_to"] < price_list.valid_from:
        raise ApiError(400, "PRICE_LIST_RANGE_INVALID", "valid_to is before valid_from")
    if "status" in data:
        data["status"] = payload.status.value

    for field, value in data.items():
        setattr(price_list, field, value)
    await session.flush()
    await commit_or_rollback(session)
    return envelope(
        await _load_price_list_detail(session, context.tenant_id, price_list.id), context
    )


@router.post("/price-lists/{price_list_id}/tiers", status_code=status.HTTP_201_CREATED)
async def create_price_tier(
    price_list_id: uuid.UUID,
    payload: PriceTierCreate,
    context: PricingUpdateContext,
    session: SessionDep,
) -> dict[str, Any]:
    price_list = await _get_price_list(session, context.tenant_id, price_list_id)
    await _ensure_product(session, context.tenant_id, payload.product_id)
    _validate_tier_ranges(
        payload.min_quantity, payload.max_quantity, payload.valid_from, payload.valid_to
    )
    await _ensure_no_tier_overlap(
        session,
        tenant_id=context.tenant_id,
        price_list_id=price_list.id,
        product_id=payload.product_id,
        min_quantity=payload.min_quantity,
        max_quantity=payload.max_quantity,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
    )

    tier = PriceTier(
        tenant_id=context.tenant_id,
        price_list_id=price_list.id,
        product_id=payload.product_id,
        min_quantity=payload.min_quantity,
        max_quantity=payload.max_quantity,
        unit_price=payload.unit_price,
        price_basis=payload.price_basis.value,
        unit=payload.unit,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
    )
    session.add(tier)
    await session.flush()
    await session.refresh(tier)
    await commit_or_rollback(session)
    return envelope(_price_tier_detail(tier), context)


@router.patch("/price-tiers/{tier_id}")
async def update_price_tier(
    tier_id: uuid.UUID,
    payload: PriceTierUpdate,
    context: PricingUpdateContext,
    session: SessionDep,
) -> dict[str, Any]:
    tier = await _get_tier(session, context.tenant_id, tier_id)
    data = payload.model_dump(exclude_unset=True)

    for field in ("min_quantity", "unit_price", "price_basis", "unit"):
        if field in data and data[field] is None:
            raise ApiError(422, "VALIDATION_ERROR", f"{field} cannot be null")

    min_quantity = data.get("min_quantity", tier.min_quantity)
    max_quantity = data["max_quantity"] if "max_quantity" in data else tier.max_quantity
    valid_from = data["valid_from"] if "valid_from" in data else tier.valid_from
    valid_to = data["valid_to"] if "valid_to" in data else tier.valid_to
    _validate_tier_ranges(min_quantity, max_quantity, valid_from, valid_to)

    await _ensure_no_tier_overlap(
        session,
        tenant_id=context.tenant_id,
        price_list_id=tier.price_list_id,
        product_id=tier.product_id,
        min_quantity=min_quantity,
        max_quantity=max_quantity,
        valid_from=valid_from,
        valid_to=valid_to,
        exclude_tier_id=tier.id,
    )

    if "price_basis" in data:
        data["price_basis"] = payload.price_basis.value
    for field, value in data.items():
        setattr(tier, field, value)
    await session.flush()
    await session.refresh(tier)
    await commit_or_rollback(session)
    return envelope(_price_tier_detail(tier), context)
