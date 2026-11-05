import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class TenantAIProviderConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenant_ai_provider_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_tenant_ai_provider_configs_tenant_id"),
        UniqueConstraint("tenant_id", "id", name="uq_tenant_ai_provider_configs_tenant_id_id"),
        CheckConstraint(
            "provider IS NULL OR provider IN ('openai', 'openai-compatible')",
            name="provider",
        ),
        CheckConstraint(
            "last_test_status IS NULL OR last_test_status IN ('SUCCESS', 'FAILED')",
            name="last_test_status",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False, server_default="openai")
    encrypted_api_key: Mapped[str | None] = mapped_column(Text)
    api_key_hint: Mapped[str | None] = mapped_column(String(40))
    base_url: Mapped[str | None] = mapped_column(String(255))
    model_id: Mapped[str | None] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_status: Mapped[str | None] = mapped_column(String(20))
    last_test_message: Mapped[str | None] = mapped_column(String(500))
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
