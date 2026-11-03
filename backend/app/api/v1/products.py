import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import commit_or_rollback, decimal_str, envelope, iso_datetime
from app.api.deps import ContextDep, SessionDep
from app.api.enums import CatalogStatus, ProductCategory
from app.api.errors import ApiError
from app.db.tenant import set_tenant_context
from app.models.product import Product

router = APIRouter(prefix="/products", tags=["products"])


class ProductCreate(BaseModel):
    product_code: str = Field(min_length=1, max_length=80)
    product_name: str = Field(min_length=1, max_length=240)
    category: ProductCategory
    standard_code: str | None = Field(default=None, max_length=80)
    material: str | None = Field(default=None, max_length=80)
    grade: str | None = Field(default=None, max_length=80)
    diameter: str | None = Field(default=None, max_length=40)
    length: str | None = Field(default=None, max_length=40)
    thread_pitch: str | None = Field(default=None, max_length=40)
    head_type: str | None = Field(default=None, max_length=80)
    drive_type: str | None = Field(default=None, max_length=80)
    surface_finish: str | None = Field(default=None, max_length=80)
    sales_unit: str = Field(min_length=1, max_length=20)
    moq: Decimal | None = Field(default=None, ge=0)
    packaging: dict[str, Any] | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    status: CatalogStatus = CatalogStatus.ACTIVE

    @field_validator("product_code", "product_name", "sales_unit")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class ProductUpdate(BaseModel):
    product_code: str | None = Field(default=None, min_length=1, max_length=80)
    product_name: str | None = Field(default=None, min_length=1, max_length=240)
    category: ProductCategory | None = None
    standard_code: str | None = Field(default=None, max_length=80)
    material: str | None = Field(default=None, max_length=80)
    grade: str | None = Field(default=None, max_length=80)
    diameter: str | None = Field(default=None, max_length=40)
    length: str | None = Field(default=None, max_length=40)
    thread_pitch: str | None = Field(default=None, max_length=40)
    head_type: str | None = Field(default=None, max_length=80)
    drive_type: str | None = Field(default=None, max_length=80)
    surface_finish: str | None = Field(default=None, max_length=80)
    sales_unit: str | None = Field(default=None, min_length=1, max_length=20)
    moq: Decimal | None = Field(default=None, ge=0)
    packaging: dict[str, Any] | None = None
    attributes: dict[str, Any] | None = None
    status: CatalogStatus | None = None

    @field_validator("product_code", "product_name", "sales_unit")
    @classmethod
    def strip_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


def _product_detail(product: Product) -> dict[str, Any]:
    return {
        "id": str(product.id),
        "product_code": product.product_code,
        "product_name": product.product_name,
        "category": product.category,
        "standard_code": product.standard_code,
        "material": product.material,
        "grade": product.grade,
        "diameter": product.diameter,
        "length": product.length,
        "thread_pitch": product.thread_pitch,
        "head_type": product.head_type,
        "drive_type": product.drive_type,
        "surface_finish": product.surface_finish,
        "sales_unit": product.sales_unit,
        "moq": decimal_str(product.moq),
        "packaging": product.packaging,
        "attributes": product.attributes,
        "status": product.status,
        "created_at": iso_datetime(product.created_at),
        "updated_at": iso_datetime(product.updated_at),
    }


async def _get_product(
    session: AsyncSession, tenant_id: uuid.UUID, product_id: uuid.UUID
) -> Product:
    await set_tenant_context(session, tenant_id)
    product = await session.scalar(
        select(Product).where(Product.tenant_id == tenant_id, Product.id == product_id)
    )
    if product is None:
        raise ApiError(404, "PRODUCT_NOT_FOUND", "product not found")
    return product


async def _ensure_code_available(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    product_code: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> None:
    statement = select(Product.id).where(
        Product.tenant_id == tenant_id,
        Product.product_code == product_code,
    )
    if exclude_id is not None:
        statement = statement.where(Product.id != exclude_id)
    if await session.scalar(statement) is not None:
        raise ApiError(409, "PRODUCT_CODE_EXISTS", "product code already exists")


@router.get("")
async def list_products(
    context: ContextDep,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    category: ProductCategory | None = None,
    status_filter: Annotated[CatalogStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
) -> dict[str, Any]:
    await set_tenant_context(session, context.tenant_id)
    conditions = [Product.tenant_id == context.tenant_id]
    if category is not None:
        conditions.append(Product.category == category.value)
    if status_filter is not None:
        conditions.append(Product.status == status_filter.value)
    if q:
        query = f"%{q.strip()}%"
        conditions.append(or_(Product.product_code.ilike(query), Product.product_name.ilike(query)))

    total = await session.scalar(select(func.count()).select_from(Product).where(*conditions))
    products = list(
        await session.scalars(
            select(Product)
            .where(*conditions)
            .order_by(Product.product_code)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return envelope(
        [_product_detail(product) for product in products],
        context,
        page=page,
        page_size=page_size,
        total=int(total or 0),
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    context: ContextDep,
    session: SessionDep,
) -> dict[str, Any]:
    await set_tenant_context(session, context.tenant_id)
    await _ensure_code_available(session, context.tenant_id, payload.product_code)

    data = payload.model_dump()
    data["category"] = payload.category.value
    data["status"] = payload.status.value
    product = Product(tenant_id=context.tenant_id, **data)
    session.add(product)
    await session.flush()
    await session.refresh(product)
    await commit_or_rollback(session)
    return envelope(_product_detail(product), context)


@router.get("/{product_id}")
async def get_product(
    product_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
) -> dict[str, Any]:
    product = await _get_product(session, context.tenant_id, product_id)
    return envelope(_product_detail(product), context)


@router.patch("/{product_id}")
async def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    context: ContextDep,
    session: SessionDep,
) -> dict[str, Any]:
    product = await _get_product(session, context.tenant_id, product_id)
    data = payload.model_dump(exclude_unset=True, exclude_none=True)

    if "product_code" in data and data["product_code"] != product.product_code:
        await _ensure_code_available(
            session, context.tenant_id, data["product_code"], exclude_id=product.id
        )
    if "category" in data:
        data["category"] = payload.category.value
    if "status" in data:
        data["status"] = payload.status.value

    for field, value in data.items():
        setattr(product, field, value)
    await session.flush()
    await session.refresh(product)
    await commit_or_rollback(session)
    return envelope(_product_detail(product), context)
