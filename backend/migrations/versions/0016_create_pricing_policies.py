"""create pricing policies

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-04 18:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pricing_policies",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column(
            "rounding_mode",
            sa.String(length=30),
            server_default="ROUND_HALF_UP",
            nullable=False,
        ),
        sa.Column("rounding_decimal_places", sa.Integer(), nullable=True),
        sa.Column(
            "moq_enforcement",
            sa.String(length=10),
            server_default="WARN",
            nullable=False,
        ),
        sa.Column(
            "max_discount_percent",
            sa.Numeric(precision=5, scale=2),
            server_default="100",
            nullable=False,
        ),
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
            "rounding_mode IN ('ROUND_HALF_UP', 'ROUND_HALF_EVEN', 'ROUND_DOWN', 'ROUND_UP')",
            name=op.f("ck_pricing_policies_rounding_mode"),
        ),
        sa.CheckConstraint(
            "rounding_decimal_places IS NULL OR rounding_decimal_places BETWEEN 0 AND 4",
            name=op.f("ck_pricing_policies_rounding_decimal_places"),
        ),
        sa.CheckConstraint(
            "moq_enforcement IN ('WARN', 'BLOCK')",
            name=op.f("ck_pricing_policies_moq_enforcement"),
        ),
        sa.CheckConstraint(
            "max_discount_percent >= 0 AND max_discount_percent <= 100",
            name=op.f("ck_pricing_policies_max_discount_percent"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_pricing_policies_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name=op.f("fk_pricing_policies_updated_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pricing_policies")),
        sa.UniqueConstraint("tenant_id", name="uq_pricing_policies_tenant_id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_pricing_policies_tenant_id_id"),
    )

    op.execute("ALTER TABLE pricing_policies ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE pricing_policies FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON pricing_policies "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid) "
        "WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.drop_table("pricing_policies")
