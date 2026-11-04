import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import envelope, iso_datetime
from app.api.deps import ContextDep, RequestContext, SessionDep, require_permission
from app.api.errors import ApiError
from app.audit import AuditService, client_ip_hash
from app.core.permissions import Permission
from app.db.session import commit_or_rollback
from app.db.tenant import set_tenant_context
from app.models.tenant import Tenant

router = APIRouter(prefix="/tenants", tags=["tenants"])

TenantUpdateContext = Annotated[
    RequestContext, Depends(require_permission(Permission.TENANT_UPDATE))
]

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_LANGUAGE_PATTERN = re.compile(r"^[a-z]{2}(-[a-z]{2})?$")
_REQUIRED_FIELDS = ("name", "default_currency", "default_language")
_MAX_MARKETS = 30
_MAX_MARKET_LENGTH = 80


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    contact_email: str | None = Field(default=None, max_length=320)
    contact_phone: str | None = Field(default=None, max_length=40)
    website: str | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=500)
    main_products: str | None = Field(default=None, max_length=500)
    export_markets: list[str] | None = None
    default_currency: str | None = Field(default=None, max_length=3)
    default_language: str | None = Field(default=None, max_length=16)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("contact_email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if _EMAIL_PATTERN.match(normalized) is None:
            raise ValueError("invalid email")
        return normalized

    @field_validator("contact_phone", "website", "address", "main_products")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("export_markets")
    @classmethod
    def normalize_markets(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        markets: list[str] = []
        seen: set[str] = set()
        for item in value:
            market = item.strip()
            if not market:
                continue
            if len(market) > _MAX_MARKET_LENGTH:
                raise ValueError(f"market exceeds {_MAX_MARKET_LENGTH} characters")
            key = market.casefold()
            if key in seen:
                continue
            seen.add(key)
            markets.append(market)
        if len(markets) > _MAX_MARKETS:
            raise ValueError(f"at most {_MAX_MARKETS} markets are allowed")
        return markets

    @field_validator("default_currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if _CURRENCY_PATTERN.fullmatch(normalized) is None:
            raise ValueError("currency must be a three-letter ISO code")
        return normalized

    @field_validator("default_language")
    @classmethod
    def normalize_language(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if _LANGUAGE_PATTERN.fullmatch(normalized) is None:
            raise ValueError("language must look like en or zh-cn")
        return normalized

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> "TenantUpdate":
        for field in _REQUIRED_FIELDS:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} must not be null")
        return self


def _tenant_detail(tenant: Tenant) -> dict[str, Any]:
    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "slug": tenant.slug,
        "status": tenant.status,
        "plan_code": tenant.plan_code,
        "contact_email": tenant.contact_email,
        "contact_phone": tenant.contact_phone,
        "website": tenant.website,
        "address": tenant.address,
        "main_products": tenant.main_products,
        "export_markets": list(tenant.export_markets or []),
        "default_currency": tenant.default_currency,
        "default_language": tenant.default_language,
        "created_at": iso_datetime(tenant.created_at),
        "updated_at": iso_datetime(tenant.updated_at),
    }


async def _get_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    await set_tenant_context(session, tenant_id)
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise ApiError(404, "TENANT_NOT_FOUND", "tenant not found")
    return tenant


@router.get("/current")
async def current_tenant(context: ContextDep, session: SessionDep) -> dict[str, Any]:
    tenant = await _get_tenant(session, context.tenant_id)
    return envelope(_tenant_detail(tenant), context)


@router.patch("/current")
async def update_current_tenant(
    payload: TenantUpdate,
    request: Request,
    context: TenantUpdateContext,
    session: SessionDep,
) -> dict[str, Any]:
    tenant = await _get_tenant(session, context.tenant_id)

    changed: list[str] = []
    for field, value in payload.model_dump(exclude_unset=True).items():
        if getattr(tenant, field) != value:
            setattr(tenant, field, value)
            changed.append(field)

    if changed:
        AuditService(session).record(
            tenant_id=context.tenant_id,
            actor_id=context.user_id,
            action="tenant.profile.updated",
            resource_type="TENANT",
            resource_id=tenant.id,
            request_id=context.request_id,
            ip_hash=client_ip_hash(request),
            metadata={"fields": changed},
        )
        await session.flush()
        await session.refresh(tenant)
        await commit_or_rollback(session)

    return envelope(_tenant_detail(tenant), context)
