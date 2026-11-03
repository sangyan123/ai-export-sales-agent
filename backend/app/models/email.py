import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class EmailDraft(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "email_drafts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_email_drafts_tenant_id_id"),
        CheckConstraint("status IN ('DRAFT', 'APPROVED')", name="status"),
        CheckConstraint(
            "status <> 'APPROVED' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)",
            name="approval_fields_required",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inquiry_id"],
            ["inquiries.tenant_id", "inquiries.id"],
            name="fk_email_drafts_tenant_inquiry",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "quote_id"],
            ["quotes.tenant_id", "quotes.id"],
            name="fk_email_drafts_tenant_quote",
            ondelete="CASCADE",
        ),
        Index(
            "ix_email_drafts_tenant_inquiry_created",
            "tenant_id",
            "inquiry_id",
            "created_at",
        ),
        Index("ix_email_drafts_tenant_status", "tenant_id", "status"),
    )

    inquiry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    quote_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    subject: Mapped[str] = mapped_column(String(240), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, server_default="en")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="DRAFT")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model_id: Mapped[str | None] = mapped_column(String(120))
    claims_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    missing_information_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    review_flags_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
