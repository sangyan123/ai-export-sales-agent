import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Inquiry(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "inquiries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_inquiries_tenant_id_id"),
        CheckConstraint(
            "source_type IN ('MANUAL', 'EMAIL', 'UPLOAD', 'OTHER')",
            name="source_type",
        ),
        CheckConstraint(
            "status IN ('RECEIVED', 'PARSING', 'NEEDS_INFO', 'READY_FOR_MATCH', "
            "'MATCHED', 'QUOTE_DRAFTED', 'PENDING_APPROVAL', 'QUOTE_APPROVED', "
            "'REPLIED', 'WON', 'LOST', 'ARCHIVED')",
            name="status",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_inquiries_tenant_customer",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_inquiries_tenant_status_received",
            "tenant_id",
            "status",
            "received_at",
        ),
        Index(
            "ix_inquiries_tenant_customer_received",
            "tenant_id",
            "customer_id",
            "received_at",
        ),
        Index(
            "ix_inquiries_tenant_owner_status",
            "tenant_id",
            "owner_user_id",
            "status",
        ),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    subject: Mapped[str] = mapped_column(String(240), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="MANUAL")
    source_ref: Mapped[str | None] = mapped_column(String(255))
    raw_body: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="RECEIVED")
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class InquiryRequirement(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "inquiry_requirements"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_inquiry_requirements_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "inquiry_id",
            "schema_version",
            name="uq_inquiry_requirements_tenant_inquiry_version",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inquiry_id"],
            ["inquiries.tenant_id", "inquiries.id"],
            name="fk_inquiry_requirements_tenant_inquiry",
            ondelete="CASCADE",
        ),
        CheckConstraint("schema_version >= 1", name="schema_version_positive"),
        Index("ix_inquiry_requirements_tenant_inquiry", "tenant_id", "inquiry_id"),
    )

    inquiry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    parsed_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    confirmed_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    confidence_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    evidence_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    model_id: Mapped[str | None] = mapped_column(String(120))


class InquiryAttachment(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "inquiry_attachments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_inquiry_attachments_tenant_id_id"),
        UniqueConstraint("tenant_id", "object_key", name="uq_inquiry_attachments_tenant_object"),
        ForeignKeyConstraint(
            ["tenant_id", "inquiry_id"],
            ["inquiries.tenant_id", "inquiries.id"],
            name="fk_inquiry_attachments_tenant_inquiry",
            ondelete="CASCADE",
        ),
        CheckConstraint("size_bytes >= 0", name="size_bytes_non_negative"),
        CheckConstraint(
            "scan_status IN ('PENDING', 'CLEAN', 'INFECTED', 'FAILED')",
            name="scan_status",
        ),
        Index(
            "ix_inquiry_attachments_tenant_inquiry",
            "tenant_id",
            "inquiry_id",
        ),
    )

    inquiry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    scan_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDING")


class InquiryMessage(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "inquiry_messages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_inquiry_messages_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "inquiry_id"],
            ["inquiries.tenant_id", "inquiries.id"],
            name="fk_inquiry_messages_tenant_inquiry",
            ondelete="CASCADE",
        ),
        CheckConstraint("direction IN ('INBOUND', 'OUTBOUND')", name="direction"),
        Index(
            "ix_inquiry_messages_tenant_inquiry_occurred",
            "tenant_id",
            "inquiry_id",
            "occurred_at",
        ),
    )

    inquiry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    sender: Mapped[str | None] = mapped_column(String(320))
    recipient: Mapped[str | None] = mapped_column(String(320))
    body: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    file_refs: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
