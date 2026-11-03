import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Quote(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_quotes_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "quote_no",
            "version_no",
            name="uq_quotes_tenant_quote_no_version",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED', "
            "'SENT', 'EXPIRED', 'CANCELLED')",
            name="status",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso4217"),
        CheckConstraint("version_no >= 1", name="version_positive"),
        CheckConstraint(
            "subtotal >= 0 AND discount_total >= 0 AND freight_total >= 0 "
            "AND other_charges >= 0 AND grand_total >= 0",
            name="amounts_non_negative",
        ),
        CheckConstraint("discount_total <= subtotal", name="discount_within_subtotal"),
        CheckConstraint(
            "grand_total = subtotal - discount_total + freight_total + other_charges",
            name="grand_total_formula",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inquiry_id"],
            ["inquiries.tenant_id", "inquiries.id"],
            name="fk_quotes_tenant_inquiry",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_quotes_tenant_status_created",
            "tenant_id",
            "status",
            "created_at",
        ),
        Index("ix_quotes_tenant_quote_no", "tenant_id", "quote_no"),
    )

    inquiry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    quote_no: Mapped[str] = mapped_column(String(40), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="DRAFT")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default="0")
    subtotal_display: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default="0"
    )
    discount_total: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default="0"
    )
    discount_total_display: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default="0"
    )
    freight_total: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default="0"
    )
    freight_total_display: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default="0"
    )
    other_charges: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default="0"
    )
    other_charges_display: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default="0"
    )
    grand_total: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default="0")
    grand_total_display: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, server_default="0"
    )
    valid_until: Mapped[date | None] = mapped_column(Date)
    terms_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    source_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class QuoteItem(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "quote_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_quote_items_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "quote_id",
            "line_no",
            name="uq_quote_items_tenant_quote_line",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "quote_id"],
            ["quotes.tenant_id", "quotes.id"],
            name="fk_quote_items_tenant_quote",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_quote_items_tenant_product",
            ondelete="RESTRICT",
        ),
        CheckConstraint("line_no >= 1", name="line_no_positive"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("priced_quantity > 0", name="priced_quantity_positive"),
        CheckConstraint(
            "unit_price >= 0 AND unit_price_display >= 0 "
            "AND line_total >= 0 AND line_total_display >= 0",
            name="amounts_non_negative",
        ),
        CheckConstraint(
            "price_basis IN ('PER_PIECE', 'PER_KG', 'PER_SET', 'PER_LOT')",
            name="price_basis",
        ),
        Index("ix_quote_items_tenant_product", "tenant_id", "product_id"),
    )

    quote_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    product_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    priced_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    price_unit: Mapped[str] = mapped_column(String(20), nullable=False)
    price_basis: Mapped[str] = mapped_column(String(20), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_price_display: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    line_total_display: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    price_source_ref: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class ApprovalTask(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "approval_tasks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_approval_tasks_tenant_id_id"),
        CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED')",
            name="status",
        ),
        CheckConstraint(
            "status NOT IN ('APPROVED', 'REJECTED') "
            "OR (approver_id IS NOT NULL AND decided_at IS NOT NULL)",
            name="decision_fields_required",
        ),
        Index(
            "ix_approval_tasks_tenant_object",
            "tenant_id",
            "object_type",
            "object_id",
        ),
        Index("ix_approval_tasks_tenant_status", "tenant_id", "status"),
    )

    object_type: Mapped[str] = mapped_column(String(40), nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approval_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDING")
    requested_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    approver_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuoteEvent(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "quote_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_quote_events_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "quote_id"],
            ["quotes.tenant_id", "quotes.id"],
            name="fk_quote_events_tenant_quote",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "event_type IN ('CREATED', 'SUBMITTED', 'APPROVED', 'REJECTED', "
            "'REVISED', 'CANCELLED', 'SENT', 'EXPIRED')",
            name="event_type",
        ),
        Index(
            "ix_quote_events_tenant_quote_created",
            "tenant_id",
            "quote_id",
            "created_at",
        ),
        Index("ix_quote_events_tenant_event", "tenant_id", "event_type"),
    )

    quote_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    event_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )
