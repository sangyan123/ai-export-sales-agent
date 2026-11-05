import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class AIUsageRecord(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "ai_usage_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_ai_usage_records_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "workflow_run_id"],
            ["workflow_runs.tenant_id", "workflow_runs.id"],
            name="fk_ai_usage_records_tenant_workflow_run",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "operation_type IN ('INQUIRY_PARSE', 'EMAIL_GENERATE')",
            name="operation_type",
        ),
        CheckConstraint("status IN ('SUCCESS', 'FAILED')", name="status"),
        CheckConstraint("prompt_tokens >= 0", name="prompt_tokens_non_negative"),
        CheckConstraint("completion_tokens >= 0", name="completion_tokens_non_negative"),
        CheckConstraint("total_tokens >= 0", name="total_tokens_non_negative"),
        CheckConstraint("duration_ms >= 0", name="duration_ms_non_negative"),
        Index("ix_ai_usage_records_tenant_created", "tenant_id", "created_at"),
        Index(
            "ix_ai_usage_records_tenant_operation",
            "tenant_id",
            "operation_type",
            "created_at",
        ),
    )

    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    operation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="SUCCESS")
    error_code: Mapped[str | None] = mapped_column(String(80))
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
