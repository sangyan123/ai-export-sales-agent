import uuid
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
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


class ProductMatch(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "product_matches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_product_matches_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "inquiry_id",
            "product_id",
            name="uq_product_matches_tenant_inquiry_product",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inquiry_id"],
            ["inquiries.tenant_id", "inquiries.id"],
            name="fk_product_matches_tenant_inquiry",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_product_matches_tenant_product",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "requirement_id"],
            ["inquiry_requirements.tenant_id", "inquiry_requirements.id"],
            name="fk_product_matches_tenant_requirement",
            ondelete="CASCADE",
        ),
        CheckConstraint("score >= 0 AND score <= 1", name="score_range"),
        CheckConstraint(
            "match_status IN ('EXACT', 'POSSIBLE', 'CONFLICT', 'NO_MATCH')",
            name="match_status",
        ),
        Index("ix_product_matches_tenant_inquiry_score", "tenant_id", "inquiry_id", "score"),
    )

    requirement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    inquiry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    score: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    match_status: Mapped[str] = mapped_column(String(20), nullable=False)
    matched_fields: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    conflict_fields: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    unknown_fields: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    explanation: Mapped[str | None] = mapped_column(Text)
