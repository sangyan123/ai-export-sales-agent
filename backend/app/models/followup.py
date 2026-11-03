import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class FollowupTask(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "followup_tasks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_followup_tasks_tenant_id_id"),
        CheckConstraint("status IN ('PENDING', 'DONE', 'CANCELLED')", name="status"),
        CheckConstraint("source IN ('MANUAL', 'RULE')", name="source"),
        CheckConstraint(
            "status <> 'DONE' OR completed_at IS NOT NULL",
            name="completed_at_required",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_followup_tasks_tenant_customer",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inquiry_id"],
            ["inquiries.tenant_id", "inquiries.id"],
            name="fk_followup_tasks_tenant_inquiry",
            ondelete="CASCADE",
        ),
        Index(
            "ix_followup_tasks_tenant_status_due",
            "tenant_id",
            "status",
            "due_at",
        ),
        Index(
            "ix_followup_tasks_tenant_customer_due",
            "tenant_id",
            "customer_id",
            "due_at",
        ),
        Index(
            "ix_followup_tasks_tenant_assignee_status",
            "tenant_id",
            "assigned_to",
            "status",
            "due_at",
        ),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    inquiry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDING")
    source: Mapped[str] = mapped_column(String(20), nullable=False, server_default="MANUAL")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
