from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
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
