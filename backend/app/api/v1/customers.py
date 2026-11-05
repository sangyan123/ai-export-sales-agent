import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import decimal_str, envelope, iso_datetime
from app.api.deps import RequestContext, SessionDep, require_permission
from app.api.enums import CatalogStatus, OverrideApprovalStatus, PriceBasis
from app.api.errors import ApiError
from app.core.permissions import Permission
from app.db.session import commit_or_rollback
from app.db.tenant import set_tenant_context
from app.models.customer import Contact, Customer, CustomerNote, CustomerPriceOverride
from app.models.product import Product
from app.models.tenant import TenantMembership

router = APIRouter(tags=["customers"])

CustomerReadContext = Annotated[
    RequestContext, Depends(require_permission(Permission.CUSTOMER_READ))
]
CustomerCreateContext = Annotated[
    RequestContext, Depends(require_permission(Permission.CUSTOMER_CREATE))
]
CustomerUpdateContext = Annotated[
    RequestContext, Depends(require_permission(Permission.CUSTOMER_UPDATE))
]
PricingUpdateContext = Annotated[
    RequestContext, Depends(require_permission(Permission.PRICING_UPDATE))
]


class CustomerCreate(BaseModel):
    company_name: str = Field(min_length=1, max_length=240)
    country_code: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    website: str | None = Field(default=None, max_length=255)
    source: str | None = Field(default=None, max_length=40)
    owner_user_id: uuid.UUID | None = None
    status: CatalogStatus = CatalogStatus.ACTIVE

    @field_validator("company_name")
    @classmethod
    def strip_company_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("country_code")
    @classmethod
    def normalize_country_code(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class CustomerUpdate(BaseModel):
    company_name: str | None = Field(default=None, min_length=1, max_length=240)
    country_code: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    website: str | None = Field(default=None, max_length=255)
    source: str | None = Field(default=None, max_length=40)
    owner_user_id: uuid.UUID | None = None
    status: CatalogStatus | None = None

    @field_validator("company_name")
    @classmethod
    def strip_company_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("country_code")
    @classmethod
    def normalize_country_code(cls, value: str | None) -> str | None:
        return value.upper() if value else None


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LANGUAGE_PATTERN = re.compile(r"^[a-z]{2}(-[a-z]{2})?$")


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class ContactCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    language: str | None = Field(default=None, max_length=16)
    job_title: str | None = Field(default=None, max_length=120)
    is_primary: bool = False

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        normalized = _normalize_optional_text(value)
        if normalized is None:
            return None
        normalized = normalized.lower()
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("invalid email address")
        return normalized

    @field_validator("phone", "job_title")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str | None) -> str | None:
        normalized = _normalize_optional_text(value)
        if normalized is None:
            return None
        normalized = normalized.lower()
        if not LANGUAGE_PATTERN.fullmatch(normalized):
            raise ValueError("language must look like 'en' or 'en-us'")
        return normalized


class ContactUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    language: str | None = Field(default=None, max_length=16)
    job_title: str | None = Field(default=None, max_length=120)
    is_primary: bool | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        normalized = _normalize_optional_text(value)
        if normalized is None:
            return None
        normalized = normalized.lower()
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("invalid email address")
        return normalized

    @field_validator("phone", "job_title")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str | None) -> str | None:
        normalized = _normalize_optional_text(value)
        if normalized is None:
            return None
        normalized = normalized.lower()
        if not LANGUAGE_PATTERN.fullmatch(normalized):
            raise ValueError("language must look like 'en' or 'en-us'")
        return normalized


class PriceOverrideCreate(BaseModel):
    product_id: uuid.UUID
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    unit_price: Decimal = Field(ge=0)
    price_basis: PriceBasis
    unit: str = Field(min_length=1, max_length=20)
    valid_from: date
    valid_to: date | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def validate_validity(self) -> "PriceOverrideCreate":
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to must not be before valid_from")
        return self


class PriceOverrideUpdate(BaseModel):
    unit_price: Decimal | None = Field(default=None, ge=0)
    price_basis: PriceBasis | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    valid_from: date | None = None
    valid_to: date | None = None


def _customer_detail(customer: Customer) -> dict[str, Any]:
    return {
        "id": str(customer.id),
        "company_name": customer.company_name,
        "country_code": customer.country_code,
        "website": customer.website,
        "source": customer.source,
        "status": customer.status,
        "owner_user_id": str(customer.owner_user_id) if customer.owner_user_id else None,
        "created_at": iso_datetime(customer.created_at),
        "updated_at": iso_datetime(customer.updated_at),
    }


def _contact_detail(contact: Contact) -> dict[str, Any]:
    return {
        "id": str(contact.id),
        "customer_id": str(contact.customer_id),
        "name": contact.name,
        "email": contact.email,
        "phone": contact.phone,
        "language": contact.language,
        "job_title": contact.job_title,
        "is_primary": contact.is_primary,
        "created_at": iso_datetime(contact.created_at),
        "updated_at": iso_datetime(contact.updated_at),
    }


def _override_detail(override: CustomerPriceOverride) -> dict[str, Any]:
    return {
        "id": str(override.id),
        "customer_id": str(override.customer_id),
        "product_id": str(override.product_id),
        "currency": override.currency,
        "unit_price": decimal_str(override.unit_price),
        "price_basis": override.price_basis,
        "unit": override.unit,
        "valid_from": override.valid_from.isoformat(),
        "valid_to": override.valid_to.isoformat() if override.valid_to else None,
        "approval_status": override.approval_status,
        "approved_by": str(override.approved_by) if override.approved_by else None,
        "approved_at": iso_datetime(override.approved_at) if override.approved_at else None,
        "created_at": iso_datetime(override.created_at),
        "updated_at": iso_datetime(override.updated_at),
    }


def _dates_overlap(start_a: date, end_a: date | None, start_b: date, end_b: date | None) -> bool:
    if end_a is not None and start_b > end_a:
        return False
    if end_b is not None and start_a > end_b:
        return False
    return True


async def _get_customer(
    session: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID
) -> Customer:
    await set_tenant_context(session, tenant_id)
    customer = await session.scalar(
        select(Customer).where(Customer.tenant_id == tenant_id, Customer.id == customer_id)
    )
    if customer is None:
        raise ApiError(404, "CUSTOMER_NOT_FOUND", "customer not found")
    return customer


async def _get_contact(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    contact_id: uuid.UUID,
) -> Contact:
    await _get_customer(session, tenant_id, customer_id)
    contact = await session.scalar(
        select(Contact).where(
            Contact.tenant_id == tenant_id,
            Contact.customer_id == customer_id,
            Contact.id == contact_id,
        )
    )
    if contact is None:
        raise ApiError(404, "CONTACT_NOT_FOUND", "contact not found")
    return contact


async def _clear_primary_contact(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    *,
    exclude_id: uuid.UUID | None = None,
) -> None:
    statement = (
        update(Contact)
        .where(
            Contact.tenant_id == tenant_id,
            Contact.customer_id == customer_id,
            Contact.is_primary.is_(True),
        )
        .values(is_primary=False)
    )
    if exclude_id is not None:
        statement = statement.where(Contact.id != exclude_id)
    await session.execute(statement)


async def _get_override(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    override_id: uuid.UUID,
) -> CustomerPriceOverride:
    await set_tenant_context(session, tenant_id)
    override = await session.scalar(
        select(CustomerPriceOverride).where(
            CustomerPriceOverride.tenant_id == tenant_id,
            CustomerPriceOverride.customer_id == customer_id,
            CustomerPriceOverride.id == override_id,
        )
    )
    if override is None:
        raise ApiError(404, "PRICE_OVERRIDE_NOT_FOUND", "price override not found")
    return override


async def _ensure_owner_member(
    session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID | None
) -> None:
    if user_id is None:
        return
    membership_id = await session.scalar(
        select(TenantMembership.id).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user_id,
            TenantMembership.status == "ACTIVE",
        )
    )
    if membership_id is None:
        raise ApiError(400, "OWNER_NOT_MEMBER", "owner is not an active tenant member")


async def _ensure_product(
    session: AsyncSession, tenant_id: uuid.UUID, product_id: uuid.UUID
) -> None:
    exists = await session.scalar(
        select(Product.id).where(Product.tenant_id == tenant_id, Product.id == product_id)
    )
    if exists is None:
        raise ApiError(404, "PRODUCT_NOT_FOUND", "product not found")


async def _ensure_unique_effective_date(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    product_id: uuid.UUID,
    currency: str,
    valid_from: date,
    exclude_id: uuid.UUID | None = None,
) -> None:
    statement = select(CustomerPriceOverride.id).where(
        CustomerPriceOverride.tenant_id == tenant_id,
        CustomerPriceOverride.customer_id == customer_id,
        CustomerPriceOverride.product_id == product_id,
        CustomerPriceOverride.currency == currency,
        CustomerPriceOverride.valid_from == valid_from,
    )
    if exclude_id is not None:
        statement = statement.where(CustomerPriceOverride.id != exclude_id)
    if await session.scalar(statement) is not None:
        raise ApiError(
            409,
            "PRICE_OVERRIDE_EXISTS",
            "an override already exists for the same customer, product, currency and valid_from",
        )


@router.get("/customers")
async def list_customers(
    context: CustomerReadContext,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    country_code: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
    status_filter: Annotated[CatalogStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
) -> dict[str, Any]:
    await set_tenant_context(session, context.tenant_id)
    conditions = [Customer.tenant_id == context.tenant_id]
    if country_code:
        conditions.append(Customer.country_code == country_code.upper())
    if status_filter is not None:
        conditions.append(Customer.status == status_filter.value)
    if q:
        pattern = f"%{q.strip()}%"
        conditions.append(
            or_(Customer.company_name.ilike(pattern), Customer.website.ilike(pattern))
        )

    total = await session.scalar(select(func.count()).select_from(Customer).where(*conditions))
    customers = list(
        await session.scalars(
            select(Customer)
            .where(*conditions)
            .order_by(Customer.company_name)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return envelope(
        [_customer_detail(customer) for customer in customers],
        context,
        page=page,
        page_size=page_size,
        total=int(total or 0),
    )


@router.post("/customers", status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreate,
    context: CustomerCreateContext,
    session: SessionDep,
) -> dict[str, Any]:
    await set_tenant_context(session, context.tenant_id)
    await _ensure_owner_member(session, context.tenant_id, payload.owner_user_id)

    data = payload.model_dump()
    data["status"] = payload.status.value
    customer = Customer(tenant_id=context.tenant_id, **data)
    session.add(customer)
    await session.flush()
    await session.refresh(customer)
    await commit_or_rollback(session)
    return envelope(_customer_detail(customer), context)


@router.get("/customers/{customer_id}")
async def get_customer(
    customer_id: uuid.UUID,
    context: CustomerReadContext,
    session: SessionDep,
) -> dict[str, Any]:
    customer = await _get_customer(session, context.tenant_id, customer_id)
    return envelope(_customer_detail(customer), context)


@router.patch("/customers/{customer_id}")
async def update_customer(
    customer_id: uuid.UUID,
    payload: CustomerUpdate,
    context: CustomerUpdateContext,
    session: SessionDep,
) -> dict[str, Any]:
    customer = await _get_customer(session, context.tenant_id, customer_id)
    data = payload.model_dump(exclude_unset=True, exclude_none=True)

    if "owner_user_id" in data:
        await _ensure_owner_member(session, context.tenant_id, data["owner_user_id"])
    if "status" in data:
        data["status"] = payload.status.value

    for field, value in data.items():
        setattr(customer, field, value)
    await session.flush()
    await session.refresh(customer)
    await commit_or_rollback(session)
    return envelope(_customer_detail(customer), context)


@router.get("/customers/{customer_id}/contacts")
async def list_contacts(
    customer_id: uuid.UUID,
    context: CustomerReadContext,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    await _get_customer(session, context.tenant_id, customer_id)
    conditions = [
        Contact.tenant_id == context.tenant_id,
        Contact.customer_id == customer_id,
    ]
    total = await session.scalar(select(func.count()).select_from(Contact).where(*conditions))
    contacts = list(
        await session.scalars(
            select(Contact)
            .where(*conditions)
            .order_by(Contact.is_primary.desc(), Contact.created_at)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return envelope(
        [_contact_detail(contact) for contact in contacts],
        context,
        page=page,
        page_size=page_size,
        total=int(total or 0),
    )


@router.post("/customers/{customer_id}/contacts", status_code=status.HTTP_201_CREATED)
async def create_contact(
    customer_id: uuid.UUID,
    payload: ContactCreate,
    context: CustomerUpdateContext,
    session: SessionDep,
) -> dict[str, Any]:
    await _get_customer(session, context.tenant_id, customer_id)
    if payload.is_primary:
        await _clear_primary_contact(session, context.tenant_id, customer_id)

    contact = Contact(
        tenant_id=context.tenant_id,
        customer_id=customer_id,
        **payload.model_dump(),
    )
    session.add(contact)
    await session.flush()
    await session.refresh(contact)
    await commit_or_rollback(session)
    return envelope(_contact_detail(contact), context)


@router.patch("/customers/{customer_id}/contacts/{contact_id}")
async def update_contact(
    customer_id: uuid.UUID,
    contact_id: uuid.UUID,
    payload: ContactUpdate,
    context: CustomerUpdateContext,
    session: SessionDep,
) -> dict[str, Any]:
    contact = await _get_contact(session, context.tenant_id, customer_id, contact_id)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is None:
        raise ApiError(422, "VALIDATION_ERROR", "name cannot be null")
    if data.get("is_primary") is True:
        await _clear_primary_contact(
            session,
            context.tenant_id,
            customer_id,
            exclude_id=contact.id,
        )

    for field, value in data.items():
        setattr(contact, field, value)
    await session.flush()
    await session.refresh(contact)
    await commit_or_rollback(session)
    return envelope(_contact_detail(contact), context)


@router.get("/customers/{customer_id}/price-overrides")
async def list_price_overrides(
    customer_id: uuid.UUID,
    context: CustomerReadContext,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    approval_status: OverrideApprovalStatus | None = None,
) -> dict[str, Any]:
    await _get_customer(session, context.tenant_id, customer_id)
    conditions = [
        CustomerPriceOverride.tenant_id == context.tenant_id,
        CustomerPriceOverride.customer_id == customer_id,
    ]
    if approval_status is not None:
        conditions.append(CustomerPriceOverride.approval_status == approval_status.value)

    total = await session.scalar(
        select(func.count()).select_from(CustomerPriceOverride).where(*conditions)
    )
    overrides = list(
        await session.scalars(
            select(CustomerPriceOverride)
            .where(*conditions)
            .order_by(CustomerPriceOverride.valid_from.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return envelope(
        [_override_detail(override) for override in overrides],
        context,
        page=page,
        page_size=page_size,
        total=int(total or 0),
    )


@router.post("/customers/{customer_id}/price-overrides", status_code=status.HTTP_201_CREATED)
async def create_price_override(
    customer_id: uuid.UUID,
    payload: PriceOverrideCreate,
    context: CustomerUpdateContext,
    session: SessionDep,
) -> dict[str, Any]:
    customer = await _get_customer(session, context.tenant_id, customer_id)
    await _ensure_product(session, context.tenant_id, payload.product_id)
    await _ensure_unique_effective_date(
        session,
        context.tenant_id,
        customer.id,
        payload.product_id,
        payload.currency,
        payload.valid_from,
    )

    override = CustomerPriceOverride(
        tenant_id=context.tenant_id,
        customer_id=customer.id,
        product_id=payload.product_id,
        currency=payload.currency,
        unit_price=payload.unit_price,
        price_basis=payload.price_basis.value,
        unit=payload.unit,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        approval_status=OverrideApprovalStatus.PENDING.value,
    )
    session.add(override)
    await session.flush()
    await session.refresh(override)
    await commit_or_rollback(session)
    return envelope(_override_detail(override), context)


@router.patch("/customers/{customer_id}/price-overrides/{override_id}")
async def update_price_override(
    customer_id: uuid.UUID,
    override_id: uuid.UUID,
    payload: PriceOverrideUpdate,
    context: CustomerUpdateContext,
    session: SessionDep,
) -> dict[str, Any]:
    override = await _get_override(session, context.tenant_id, customer_id, override_id)
    if override.approval_status != OverrideApprovalStatus.PENDING.value:
        raise ApiError(409, "PRICE_OVERRIDE_NOT_PENDING", "only pending overrides can be changed")

    data = payload.model_dump(exclude_unset=True)
    for field in ("unit_price", "price_basis", "unit", "valid_from"):
        if field in data and data[field] is None:
            raise ApiError(422, "VALIDATION_ERROR", f"{field} cannot be null")

    valid_from = data.get("valid_from", override.valid_from)
    valid_to = data["valid_to"] if "valid_to" in data else override.valid_to
    if valid_to is not None and valid_to < valid_from:
        raise ApiError(400, "PRICE_OVERRIDE_RANGE_INVALID", "valid_to is before valid_from")

    if "valid_from" in data:
        await _ensure_unique_effective_date(
            session,
            context.tenant_id,
            override.customer_id,
            override.product_id,
            override.currency,
            valid_from,
            exclude_id=override.id,
        )
    if "price_basis" in data:
        data["price_basis"] = payload.price_basis.value

    for field, value in data.items():
        setattr(override, field, value)
    await session.flush()
    await session.refresh(override)
    await commit_or_rollback(session)
    return envelope(_override_detail(override), context)


@router.post("/customers/{customer_id}/price-overrides/{override_id}/approve")
async def approve_price_override(
    customer_id: uuid.UUID,
    override_id: uuid.UUID,
    context: PricingUpdateContext,
    session: SessionDep,
) -> dict[str, Any]:
    override = await _get_override(session, context.tenant_id, customer_id, override_id)
    if override.approval_status != OverrideApprovalStatus.PENDING.value:
        raise ApiError(409, "PRICE_OVERRIDE_NOT_PENDING", "only pending overrides can be approved")

    approved = list(
        await session.scalars(
            select(CustomerPriceOverride).where(
                CustomerPriceOverride.tenant_id == context.tenant_id,
                CustomerPriceOverride.customer_id == override.customer_id,
                CustomerPriceOverride.product_id == override.product_id,
                CustomerPriceOverride.currency == override.currency,
                CustomerPriceOverride.approval_status == OverrideApprovalStatus.APPROVED.value,
                CustomerPriceOverride.id != override.id,
            )
        )
    )
    for other in approved:
        if _dates_overlap(override.valid_from, override.valid_to, other.valid_from, other.valid_to):
            raise ApiError(
                409,
                "PRICE_OVERRIDE_AMBIGUOUS",
                "another approved override overlaps this validity period",
            )

    override.approval_status = OverrideApprovalStatus.APPROVED.value
    override.approved_by = context.user_id
    override.approved_at = datetime.now(UTC)
    await session.flush()
    await session.refresh(override)
    await commit_or_rollback(session)
    return envelope(_override_detail(override), context)


@router.post("/customers/{customer_id}/price-overrides/{override_id}/reject")
async def reject_price_override(
    customer_id: uuid.UUID,
    override_id: uuid.UUID,
    context: PricingUpdateContext,
    session: SessionDep,
) -> dict[str, Any]:
    override = await _get_override(session, context.tenant_id, customer_id, override_id)
    if override.approval_status != OverrideApprovalStatus.PENDING.value:
        raise ApiError(409, "PRICE_OVERRIDE_NOT_PENDING", "only pending overrides can be rejected")

    override.approval_status = OverrideApprovalStatus.REJECTED.value
    await session.flush()
    await session.refresh(override)
    await commit_or_rollback(session)
    return envelope(_override_detail(override), context)

# ---------------------------------------------------------------------------
# Customer Notes (备注 / 时间线)
# ---------------------------------------------------------------------------


class NoteCreate(BaseModel):
    content: str = Field(min_length=1, max_length=5000)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class NoteUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=5000)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


def _note_detail(note: CustomerNote) -> dict[str, Any]:
    return {
        "id": str(note.id),
        "customer_id": str(note.customer_id),
        "author_id": str(note.author_id) if note.author_id else None,
        "content": note.content,
        "created_at": iso_datetime(note.created_at),
        "updated_at": iso_datetime(note.updated_at),
    }


async def _get_note(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    note_id: uuid.UUID,
) -> CustomerNote:
    note = await session.scalar(
        select(CustomerNote).where(
            CustomerNote.tenant_id == tenant_id,
            CustomerNote.customer_id == customer_id,
            CustomerNote.id == note_id,
        )
    )
    if note is None:
        raise ApiError(404, "NOTE_NOT_FOUND", "customer note not found")
    return note


@router.get("/customers/{customer_id}/notes")
async def list_notes(
    customer_id: uuid.UUID,
    context: CustomerReadContext,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    await _get_customer(session, context.tenant_id, customer_id)
    conditions = [
        CustomerNote.tenant_id == context.tenant_id,
        CustomerNote.customer_id == customer_id,
    ]
    total = await session.scalar(select(func.count()).select_from(CustomerNote).where(*conditions))
    notes = list(
        await session.scalars(
            select(CustomerNote)
            .where(*conditions)
            .order_by(CustomerNote.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return envelope(
        [_note_detail(note) for note in notes],
        context,
        page=page,
        page_size=page_size,
        total=int(total or 0),
    )


@router.post("/customers/{customer_id}/notes", status_code=status.HTTP_201_CREATED)
async def create_note(
    customer_id: uuid.UUID,
    payload: NoteCreate,
    context: CustomerUpdateContext,
    session: SessionDep,
) -> dict[str, Any]:
    await _get_customer(session, context.tenant_id, customer_id)
    note = CustomerNote(
        tenant_id=context.tenant_id,
        customer_id=customer_id,
        author_id=context.user_id,
        content=payload.content,
    )
    session.add(note)
    await session.flush()
    await session.refresh(note)
    await commit_or_rollback(session)
    return envelope(_note_detail(note), context)


@router.patch("/customers/{customer_id}/notes/{note_id}")
async def update_note(
    customer_id: uuid.UUID,
    note_id: uuid.UUID,
    payload: NoteUpdate,
    context: CustomerUpdateContext,
    session: SessionDep,
) -> dict[str, Any]:
    note = await _get_note(session, context.tenant_id, customer_id, note_id)
    note.content = payload.content
    await session.flush()
    await session.refresh(note)
    await commit_or_rollback(session)
    return envelope(_note_detail(note), context)


@router.delete("/customers/{customer_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    customer_id: uuid.UUID,
    note_id: uuid.UUID,
    context: CustomerUpdateContext,
    session: SessionDep,
) -> None:
    note = await _get_note(session, context.tenant_id, customer_id, note_id)
    await session.delete(note)
    await commit_or_rollback(session)
