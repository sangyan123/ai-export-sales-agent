import uuid

from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Product(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_code", name="uq_products_tenant_product_code"),
        UniqueConstraint("tenant_id", "id", name="uq_products_tenant_id_id"),
        CheckConstraint("category IN ('BOLT', 'NUT', 'SCREW', 'WASHER', 'OTHER')", name="category"),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE', 'ARCHIVED')", name="status"),
        CheckConstraint("moq IS NULL OR moq >= 0", name="moq_non_negative"),
        Index("ix_products_tenant_category_status", "tenant_id", "category", "status"),
        Index(
            "ix_products_tenant_standard_material",
            "tenant_id",
            "standard_code",
            "material",
        ),
    )

    product_code: Mapped[str] = mapped_column(String(80), nullable=False)
    product_name: Mapped[str] = mapped_column(String(240), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    standard_code: Mapped[str | None] = mapped_column(String(80))
    material: Mapped[str | None] = mapped_column(String(80))
    grade: Mapped[str | None] = mapped_column(String(80))
    diameter: Mapped[str | None] = mapped_column(String(40))
    length: Mapped[str | None] = mapped_column(String(40))
    thread_pitch: Mapped[str | None] = mapped_column(String(40))
    head_type: Mapped[str | None] = mapped_column(String(80))
    drive_type: Mapped[str | None] = mapped_column(String(80))
    surface_finish: Mapped[str | None] = mapped_column(String(80))
    sales_unit: Mapped[str] = mapped_column(String(20), nullable=False)
    moq: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    packaging: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ACTIVE")


class KnowledgeDocument(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_knowledge_documents_tenant_id_id"),
        UniqueConstraint("tenant_id", "object_key", name="uq_knowledge_documents_tenant_object"),
        CheckConstraint("size_bytes >= 0", name="size_bytes_non_negative"),
        CheckConstraint(
            "source IN ('CATALOG', 'PRICE_LIST', 'CERTIFICATE', 'SPEC_SHEET', 'OTHER')",
            name="source_category",
        ),
        CheckConstraint(
            "parse_status IN ('UPLOADED', 'PARSED', 'FAILED')",
            name="parse_status",
        ),
        Index(
            "ix_knowledge_documents_tenant_source",
            "tenant_id",
            "source",
        ),
        Index(
            "ix_knowledge_documents_tenant_created",
            "tenant_id",
            "created_at",
        ),
    )

    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, server_default="OTHER")
    description: Mapped[str | None] = mapped_column(String(500))
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="UPLOADED")
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
