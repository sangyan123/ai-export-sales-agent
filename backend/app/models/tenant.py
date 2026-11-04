import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'SUSPENDED', 'ARCHIVED')", name="status"),
        CheckConstraint(
            "contact_email IS NULL OR "
            "contact_email ~* '^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$'",
            name="contact_email_format",
        ),
        CheckConstraint("default_currency ~ '^[A-Z]{3}$'", name="default_currency_format"),
        CheckConstraint(
            "default_language ~ '^[a-z]{2}(-[A-Za-z]{2})?$'", name="default_language_format"
        ),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ACTIVE")
    plan_code: Mapped[str | None] = mapped_column(String(40))
    contact_email: Mapped[str | None] = mapped_column(String(320))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    website: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(500))
    main_products: Mapped[str | None] = mapped_column(String(500))
    export_markets: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    default_currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="USD")
    default_language: Mapped[str] = mapped_column(String(16), nullable=False, server_default="en")


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint("status IN ('ACTIVE', 'DISABLED')", name="status"),
    )

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ACTIVE")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TenantMembership(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "tenant_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_tenant_memberships_tenant_user"),
        UniqueConstraint("tenant_id", "id", name="uq_tenant_memberships_tenant_id_id"),
        CheckConstraint(
            "role_code IN ('OWNER', 'TENANT_ADMIN', 'SALES_MANAGER', 'SALES_REP', "
            "'APPROVER', 'VIEWER')",
            name="role_code",
        ),
        CheckConstraint("status IN ('INVITED', 'ACTIVE', 'DISABLED')", name="status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    role_code: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ACTIVE")
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
