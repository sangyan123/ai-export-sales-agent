import uuid
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tenant import set_tenant_context
from app.models.product import Product
from app.models.workflow import WorkflowRun
from app.products import (
    ProductImportError,
    ProductImportErrorCode,
    ProductImportRowErrorCode,
)
from app.workflows import WorkflowStatus

WORKFLOW_TYPE = "PRODUCT_IMPORT"
BUSINESS_OBJECT_TYPE = "TENANT"
MAX_ROWS = 5000
MAX_ERRORS = 100
VALIDATION_FAILED_CODE = "IMPORT_VALIDATION_FAILED"

COLUMN_DEFINITIONS: tuple[tuple[str, str, str], ...] = (
    ("product_code", "产品编码", "必填，租户内唯一，最长 80 字符"),
    ("product_name", "产品名称", "必填，最长 240 字符"),
    ("category", "产品类别", "必填，可选 BOLT / NUT / SCREW / WASHER / OTHER，也接受中文名称"),
    ("standard_code", "标准号", "选填，最长 80 字符"),
    ("material", "材质", "选填，最长 80 字符"),
    ("grade", "等级", "选填，最长 80 字符"),
    ("diameter", "直径", "选填，最长 40 字符"),
    ("length", "长度", "选填，最长 40 字符"),
    ("thread_pitch", "螺距", "选填，最长 40 字符"),
    ("head_type", "头型", "选填，最长 80 字符"),
    ("drive_type", "驱动类型", "选填，最长 80 字符"),
    ("surface_finish", "表面处理", "选填，最长 80 字符"),
    ("sales_unit", "计价单位", "必填，最长 20 字符"),
    ("moq", "MOQ", "选填，非负数字，最多 4 位小数"),
)

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    field: (header, field) for field, header, _ in COLUMN_DEFINITIONS
}
_ALIAS_TO_FIELD = {
    alias.casefold(): field for field, aliases in COLUMN_ALIASES.items() for alias in aliases
}

REQUIRED_FIELDS = ("product_code", "product_name", "category", "sales_unit")
FIELD_LIMITS = {
    "product_code": 80,
    "product_name": 240,
    "standard_code": 80,
    "material": 80,
    "grade": 80,
    "diameter": 40,
    "length": 40,
    "thread_pitch": 40,
    "head_type": 80,
    "drive_type": 80,
    "surface_finish": 80,
    "sales_unit": 20,
}
CATEGORIES = frozenset({"BOLT", "NUT", "SCREW", "WASHER", "OTHER"})
CATEGORY_ALIASES = {
    "螺栓": "BOLT",
    "螺母": "NUT",
    "螺钉": "SCREW",
    "螺丝": "SCREW",
    "垫圈": "WASHER",
    "垫片": "WASHER",
    "其他": "OTHER",
}
PRODUCT_FIELDS = tuple(field for field, _, _ in COLUMN_DEFINITIONS)
_MOQ_QUANTUM = Decimal("0.0001")


def _template_header(field: str) -> str:
    return COLUMN_ALIASES[field][0]


def _cell_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        text = str(value)
    elif isinstance(value, float) and value.is_integer():
        text = str(int(value))
    elif isinstance(value, Decimal):
        text = format(value, "f")
    else:
        text = str(value)
    text = text.strip()
    return text or None


def _normalize_category(value: str) -> str | None:
    candidate = value.strip()
    if candidate.upper() in CATEGORIES:
        return candidate.upper()
    return CATEGORY_ALIASES.get(candidate)


def _parse_moq(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("boolean moq")
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid moq") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("invalid moq")
    try:
        if amount != amount.quantize(_MOQ_QUANTUM):
            raise ValueError("invalid moq scale")
    except InvalidOperation as exc:
        raise ValueError("invalid moq") from exc
    return amount


def _parse_rows(data: bytes) -> list[dict[str, Any]]:
    try:
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except (InvalidFileException, BadZipFile, KeyError, OSError, ValueError) as exc:
        raise ProductImportError(
            ProductImportErrorCode.IMPORT_TEMPLATE_INVALID,
            "workbook cannot be parsed as xlsx",
        ) from exc

    try:
        worksheet = workbook.active
        if worksheet is None:
            raise ProductImportError(
                ProductImportErrorCode.IMPORT_TEMPLATE_INVALID, "workbook has no worksheet"
            )
        row_iterator = worksheet.iter_rows(values_only=True)
        header = next(row_iterator, None)
        if header is None:
            raise ProductImportError(
                ProductImportErrorCode.IMPORT_TEMPLATE_INVALID, "worksheet is empty"
            )

        columns: dict[str, int] = {}
        for index, value in enumerate(header):
            if value is None:
                continue
            field = _ALIAS_TO_FIELD.get(str(value).strip().casefold())
            if field is None:
                continue
            if field in columns:
                raise ProductImportError(
                    ProductImportErrorCode.IMPORT_TEMPLATE_INVALID,
                    f"worksheet contains duplicate column: {_template_header(field)}",
                )
            columns[field] = index

        missing = [field for field in REQUIRED_FIELDS if field not in columns]
        if missing:
            labels = "、".join(_template_header(field) for field in missing)
            raise ProductImportError(
                ProductImportErrorCode.IMPORT_TEMPLATE_INVALID,
                f"worksheet is missing required columns: {labels}",
            )

        records: list[dict[str, Any]] = []
        for number, row in enumerate(row_iterator, start=2):
            record: dict[str, Any] = {}
            has_value = False
            for field, index in columns.items():
                value = row[index] if index < len(row) else None
                if field == "moq":
                    record["moq"] = value
                    has_value = has_value or _cell_text(value) is not None
                    continue
                text = _cell_text(value)
                record[field] = text
                has_value = has_value or text is not None
            if not has_value:
                continue
            if len(records) >= MAX_ROWS:
                raise ProductImportError(
                    ProductImportErrorCode.IMPORT_TOO_MANY_ROWS,
                    f"at most {MAX_ROWS} product rows are allowed",
                )
            record["__row__"] = number
            records.append(record)

        if not records:
            raise ProductImportError(
                ProductImportErrorCode.IMPORT_EMPTY, "no product rows found in the file"
            )
        return records
    finally:
        workbook.close()


def _row_error(
    row: int, field: str | None, code: ProductImportRowErrorCode, message: str
) -> dict[str, Any]:
    return {"row": row, "field": field, "code": code.value, "message": message}


def _validate_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    code_counts = Counter(
        record["product_code"] for record in records if record.get("product_code") is not None
    )

    for record in records:
        row = record["__row__"]
        for field in REQUIRED_FIELDS:
            if record.get(field) is None:
                errors.append(
                    _row_error(
                        row,
                        field,
                        ProductImportRowErrorCode.REQUIRED,
                        f"{field} is required",
                    )
                )

        category = record.get("category")
        if category is not None:
            normalized = _normalize_category(category)
            if normalized is None:
                errors.append(
                    _row_error(
                        row,
                        "category",
                        ProductImportRowErrorCode.INVALID_CATEGORY,
                        "category must be one of BOLT, NUT, SCREW, WASHER, OTHER",
                    )
                )
            else:
                record["category"] = normalized

        for field, limit in FIELD_LIMITS.items():
            value = record.get(field)
            if value is not None and len(value) > limit:
                errors.append(
                    _row_error(
                        row,
                        field,
                        ProductImportRowErrorCode.TOO_LONG,
                        f"{field} exceeds {limit} characters",
                    )
                )

        moq_value = record.get("moq")
        if moq_value is None or (isinstance(moq_value, str) and not moq_value.strip()):
            record["moq"] = None
        else:
            try:
                record["moq"] = _parse_moq(record["moq"])
            except ValueError:
                record["moq"] = None
                errors.append(
                    _row_error(
                        row,
                        "moq",
                        ProductImportRowErrorCode.INVALID_MOQ,
                        "moq must be a non-negative number with at most 4 decimals",
                    )
                )

        code = record.get("product_code")
        if code is not None and code_counts[code] > 1:
            errors.append(
                _row_error(
                    row,
                    "product_code",
                    ProductImportRowErrorCode.DUPLICATE_PRODUCT_CODE,
                    f"product_code {code} is duplicated in the file",
                )
            )

    return errors


class ProductImportService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def import_workbook(
        self,
        *,
        tenant_id: uuid.UUID,
        requested_by: uuid.UUID,
        filename: str,
        data: bytes,
        request_id: str | None = None,
    ) -> WorkflowRun:
        await set_tenant_context(self._session, tenant_id)
        records = _parse_rows(data)
        errors = _validate_records(records)
        errors.extend(await self._existing_code_errors(tenant_id, records))

        run = WorkflowRun(
            tenant_id=tenant_id,
            workflow_type=WORKFLOW_TYPE,
            business_object_type=BUSINESS_OBJECT_TYPE,
            business_object_id=tenant_id,
            status=WorkflowStatus.QUEUED.value,
            input_ref={
                "filename": filename,
                "size_bytes": len(data),
                "request_id": request_id,
            },
            requested_by=requested_by,
        )
        self._session.add(run)

        now = datetime.now(UTC)
        run.started_at = now
        run.finished_at = now
        failed_rows = {error["row"] for error in errors}
        if not errors:
            for record in records:
                self._session.add(
                    Product(
                        tenant_id=tenant_id,
                        **{field: record.get(field) for field in PRODUCT_FIELDS},
                    )
                )
            run.status = WorkflowStatus.SUCCEEDED.value
        else:
            run.status = WorkflowStatus.FAILED.value
            run.error_code = VALIDATION_FAILED_CODE

        run.output_ref = {
            "filename": filename,
            "size_bytes": len(data),
            "total_rows": len(records),
            "imported": 0 if errors else len(records),
            "failed": len(failed_rows),
            "errors": errors[:MAX_ERRORS],
            "errors_truncated": len(errors) > MAX_ERRORS,
        }
        await self._session.flush()
        await self._session.refresh(run)
        return run

    async def get_job(self, *, tenant_id: uuid.UUID, job_id: uuid.UUID) -> WorkflowRun:
        await set_tenant_context(self._session, tenant_id)
        run = await self._session.scalar(
            select(WorkflowRun).where(
                WorkflowRun.tenant_id == tenant_id,
                WorkflowRun.id == job_id,
                WorkflowRun.workflow_type == WORKFLOW_TYPE,
            )
        )
        if run is None:
            raise ProductImportError(
                ProductImportErrorCode.PRODUCT_IMPORT_NOT_FOUND, "import job not found"
            )
        return run

    async def _existing_code_errors(
        self, tenant_id: uuid.UUID, records: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        codes = {record["product_code"] for record in records if record.get("product_code")}
        if not codes:
            return []
        existing = set(
            await self._session.scalars(
                select(Product.product_code).where(
                    Product.tenant_id == tenant_id,
                    Product.product_code.in_(codes),
                )
            )
        )
        return [
            _row_error(
                record["__row__"],
                "product_code",
                ProductImportRowErrorCode.PRODUCT_CODE_EXISTS,
                f"product_code {record['product_code']} already exists",
            )
            for record in records
            if record.get("product_code") in existing
        ]


__all__ = [
    "COLUMN_DEFINITIONS",
    "MAX_ROWS",
    "ProductImportService",
    "WORKFLOW_TYPE",
]
