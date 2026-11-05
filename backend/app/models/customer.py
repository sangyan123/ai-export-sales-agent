import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Customer(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_customers_tenant_id_id"),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE', 'ARCHIVED')", name="status"),
        CheckConstraint(
            "country_code IS NULL OR country_code ~ '^[A-Z]{2}$'",
            name="country_code_iso3166",
        ),
        Index("ix_customers_tenant_company_name", "tenant_id", "company_name"),
        Index("ix_customers_tenant_country", "tenant_id", "country_code"),
    )

    company_name: Mapped[str] = mapped_column(String(240), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2))
    website: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ACTIVE")
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class Contact(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_contacts_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_contacts_tenant_customer",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "email IS NULL OR email ~* '^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$'",
            name="email_format",
        ),
        CheckConstraint(
            "language IS NULL OR language ~ '^[a-z]{2}(-[A-Za-z]{2})?$'",
            name="language_format",
        ),
        Index("ix_contacts_tenant_customer", "tenant_id", "customer_id"),
        Index(
            "uq_contacts_tenant_customer_primary",
            "tenant_id",
            "customer_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(40))
    language: Mapped[str | None] = mapped_column(String(16))
    job_title: Mapped[str | None] = mapped_column(String(120))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class CustomerPriceOverride(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "customer_price_overrides"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_customer_price_overrides_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "customer_id",
            "product_id",
            "currency",
            "valid_from",
            name="uq_customer_price_overrides_effective_from",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_customer_price_overrides_tenant_customer",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_customer_price_overrides_tenant_product",
            ondelete="RESTRICT",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso4217"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint(
            "price_basis IN ('PER_PIECE', 'PER_KG', 'PER_SET', 'PER_LOT')",
            name="price_basis",
        ),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="validity_range"),
        CheckConstraint(
            "approval_status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name="approval_status",
        ),
        Index(
            "ix_customer_price_overrides_lookup",
            "tenant_id",
            "customer_id",
            "product_id",
            "currency",
            "approval_status",
        ),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    price_basis: Mapped[str] = mapped_column(String(20), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    approval_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="PENDING"
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CustomerNote(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "customer_notes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_customer_notes_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_customer_notes_tenant_customer",
            ondelete="CASCADE",
        ),
        Index("ix_customer_notes_tenant_customer_created", "tenant_id", "customer_id", "created_at"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
