from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.api.deps import RequestContext


def iso_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def decimal_str(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def envelope_meta(request_id: str) -> dict[str, str]:
    return {
        "request_id": request_id,
        "timestamp": iso_datetime(datetime.now(UTC)),
    }


def envelope(
    data: Any,
    context: RequestContext,
    *,
    page: int | None = None,
    page_size: int | None = None,
    total: int | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = envelope_meta(context.request_id)
    if page is not None:
        meta.update({"page": page, "page_size": page_size, "total": total})
    return {"data": data, "meta": meta}
