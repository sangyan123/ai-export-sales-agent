import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class PriceList(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "price_lists"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_price_lists_tenant_id_id"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso4217"),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="validity_range"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE', 'ARCHIVED')", name="status"),
        Index("ix_price_lists_tenant_status", "tenant_id", "status"),
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ACTIVE")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class PriceTier(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "price_tiers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_price_tiers_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "price_list_id"],
            ["price_lists.tenant_id", "price_lists.id"],
            name="fk_price_tiers_tenant_price_list",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_price_tiers_tenant_product",
            ondelete="CASCADE",
        ),
        CheckConstraint("min_quantity >= 0", name="min_quantity_non_negative"),
        CheckConstraint(
            "max_quantity IS NULL OR max_quantity > min_quantity", name="quantity_range"
        ),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint(
            "price_basis IN ('PER_PIECE', 'PER_KG', 'PER_SET', 'PER_LOT')",
            name="price_basis",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="validity_range",
        ),
        Index(
            "ix_price_tiers_tenant_product_min",
            "tenant_id",
            "product_id",
            "min_quantity",
        ),
    )

    price_list_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    min_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    max_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    price_basis: Mapped[str] = mapped_column(String(20), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
