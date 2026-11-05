"""create tenant ai provider configs

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-05 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_ai_provider_configs",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=40), server_default="openai", nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=True),
        sa.Column("api_key_hint", sa.String(length=40), nullable=True),
        sa.Column("base_url", sa.String(length=255), nullable=True),
        sa.Column("model_id", sa.String(length=120), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_status", sa.String(length=20), nullable=True),
        sa.Column("last_test_message", sa.String(length=500), nullable=True),
        sa.Column("updated_by_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provider IS NULL OR provider IN ('openai', 'openai-compatible')",
            name=op.f("ck_tenant_ai_provider_configs_provider"),
        ),
        sa.CheckConstraint(
            "last_test_status IS NULL OR last_test_status IN ('SUCCESS', 'FAILED')",
            name=op.f("ck_tenant_ai_provider_configs_last_test_status"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_tenant_ai_provider_configs_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name=op.f("fk_tenant_ai_provider_configs_updated_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_ai_provider_configs")),
        sa.UniqueConstraint("tenant_id", name="uq_tenant_ai_provider_configs_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_tenant_ai_provider_configs_tenant_id_id"
        ),
    )

    op.execute("ALTER TABLE tenant_ai_provider_configs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_ai_provider_configs FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON tenant_ai_provider_configs "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid) "
        "WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.drop_table("tenant_ai_provider_configs")
