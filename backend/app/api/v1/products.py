import uuid
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import decimal_str, envelope, iso_datetime
from app.api.deps import RequestContext, SessionDep, require_permission
from app.api.enums import CatalogStatus, ProductCategory
from app.api.errors import ApiError
from app.audit import AuditService, client_ip_hash
from app.core.config import settings
from app.core.permissions import Permission
from app.db.session import commit_or_rollback
from app.db.tenant import set_tenant_context
from app.models.product import Product
from app.models.workflow import WorkflowRun
from app.products import ProductImportError, ProductImportErrorCode
from app.products.importer import ProductImportService
from app.products.template import render_import_template

router = APIRouter(prefix="/products", tags=["products"])

ProductReadContext = Annotated[RequestContext, Depends(require_permission(Permission.PRODUCT_READ))]
ProductCreateContext = Annotated[
    RequestContext, Depends(require_permission(Permission.PRODUCT_CREATE))
]
ProductUpdateContext = Annotated[
    RequestContext, Depends(require_permission(Permission.PRODUCT_UPDATE))
]
ProductImportContext = Annotated[
    RequestContext, Depends(require_permission(Permission.PRODUCT_IMPORT))
]

IMPORT_SUFFIXES = frozenset({".xlsx", ".xlsm"})
IMPORT_TEMPLATE_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
IMPORT_READ_CHUNK_BYTES = 1024 * 1024


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
    context: ProductReadContext,
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
    context: ProductCreateContext,
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


async def _read_import_file(file: UploadFile) -> tuple[str, bytes]:
    filename = (file.filename or "").strip()
    if not filename:
        raise ProductImportError(
            ProductImportErrorCode.IMPORT_FILE_REQUIRED, "product import file is required"
        )
    if Path(filename).suffix.lower() not in IMPORT_SUFFIXES:
        raise ProductImportError(
            ProductImportErrorCode.IMPORT_FILE_UNSUPPORTED,
            "only .xlsx or .xlsm files are supported",
        )

    buffer = bytearray()
    while chunk := await file.read(IMPORT_READ_CHUNK_BYTES):
        buffer.extend(chunk)
        if len(buffer) > settings.attachment_max_bytes:
            raise ProductImportError(
                ProductImportErrorCode.IMPORT_FILE_TOO_LARGE,
                f"product import file exceeds {settings.attachment_max_bytes} bytes",
            )
    if not buffer:
        raise ProductImportError(
            ProductImportErrorCode.IMPORT_TEMPLATE_INVALID, "product import file is empty"
        )
    return filename[:255], bytes(buffer)


def _import_detail(run: WorkflowRun) -> dict[str, Any]:
    output = run.output_ref or {}
    return {
        "id": str(run.id),
        "status": run.status,
        "filename": output.get("filename"),
        "total_rows": output.get("total_rows", 0),
        "imported": output.get("imported", 0),
        "failed": output.get("failed", 0),
        "errors": output.get("errors", []),
        "errors_truncated": output.get("errors_truncated", False),
        "error_code": run.error_code,
        "requested_by": str(run.requested_by) if run.requested_by else None,
        "started_at": iso_datetime(run.started_at) if run.started_at else None,
        "finished_at": iso_datetime(run.finished_at) if run.finished_at else None,
        "created_at": iso_datetime(run.created_at),
        "updated_at": iso_datetime(run.updated_at),
    }


def _record_import_audit(
    request: Request,
    context: RequestContext,
    session: AsyncSession,
    run: WorkflowRun,
) -> None:
    output = run.output_ref or {}
    AuditService(session).record(
        tenant_id=context.tenant_id,
        actor_id=context.user_id,
        action="product.import",
        resource_type="PRODUCT_IMPORT",
        resource_id=run.id,
        request_id=context.request_id,
        ip_hash=client_ip_hash(request),
        metadata={
            "status": run.status,
            "filename": output.get("filename"),
            "total_rows": output.get("total_rows"),
            "imported": output.get("imported"),
            "failed": output.get("failed"),
        },
    )


@router.post("/imports", status_code=status.HTTP_201_CREATED)
async def import_products(
    file: Annotated[UploadFile, File()],
    context: ProductImportContext,
    session: SessionDep,
    request: Request,
) -> dict[str, Any]:
    filename, data = await _read_import_file(file)
    run = await ProductImportService(session).import_workbook(
        tenant_id=context.tenant_id,
        requested_by=context.user_id,
        filename=filename,
        data=data,
        request_id=context.request_id,
    )
    _record_import_audit(request, context, session, run)
    await commit_or_rollback(session)
    return envelope(_import_detail(run), context)


@router.get("/imports/{job_id}")
async def get_product_import_job(
    job_id: uuid.UUID,
    context: ProductReadContext,
    session: SessionDep,
) -> dict[str, Any]:
    run = await ProductImportService(session).get_job(tenant_id=context.tenant_id, job_id=job_id)
    return envelope(_import_detail(run), context)


@router.get("/import-template")
async def download_product_import_template(context: ProductReadContext) -> StreamingResponse:
    return StreamingResponse(
        BytesIO(render_import_template()),
        media_type=IMPORT_TEMPLATE_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="product-import-template.xlsx"'},
    )


@router.get("/{product_id}")
async def get_product(
    product_id: uuid.UUID,
    context: ProductReadContext,
    session: SessionDep,
) -> dict[str, Any]:
    product = await _get_product(session, context.tenant_id, product_id)
    return envelope(_product_detail(product), context)


@router.patch("/{product_id}")
async def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    context: ProductUpdateContext,
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
