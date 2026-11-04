"""add tenant profile fields

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-04 11:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("contact_email", sa.String(length=320), nullable=True))
    op.add_column("tenants", sa.Column("contact_phone", sa.String(length=40), nullable=True))
    op.add_column("tenants", sa.Column("website", sa.String(length=255), nullable=True))
    op.add_column("tenants", sa.Column("address", sa.String(length=500), nullable=True))
    op.add_column("tenants", sa.Column("main_products", sa.String(length=500), nullable=True))
    op.add_column(
        "tenants",
        sa.Column(
            "export_markets",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "tenants",
        sa.Column("default_currency", sa.String(length=3), server_default="USD", nullable=False),
    )
    op.add_column(
        "tenants",
        sa.Column("default_language", sa.String(length=16), server_default="en", nullable=False),
    )

    op.create_check_constraint(
        op.f("ck_tenants_contact_email_format"),
        "tenants",
        "contact_email IS NULL OR "
        "contact_email ~* '^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$'",
    )
    op.create_check_constraint(
        op.f("ck_tenants_default_currency_format"),
        "tenants",
        "default_currency ~ '^[A-Z]{3}$'",
    )
    op.create_check_constraint(
        op.f("ck_tenants_default_language_format"),
        "tenants",
        "default_language ~ '^[a-z]{2}(-[A-Za-z]{2})?$'",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_tenants_default_language_format"), "tenants", type_="check")
    op.drop_constraint(op.f("ck_tenants_default_currency_format"), "tenants", type_="check")
    op.drop_constraint(op.f("ck_tenants_contact_email_format"), "tenants", type_="check")
    op.drop_column("tenants", "default_language")
    op.drop_column("tenants", "default_currency")
    op.drop_column("tenants", "export_markets")
    op.drop_column("tenants", "main_products")
    op.drop_column("tenants", "address")
    op.drop_column("tenants", "website")
    op.drop_column("tenants", "contact_phone")
    op.drop_column("tenants", "contact_email")
