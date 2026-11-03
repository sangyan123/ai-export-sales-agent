"""create workflow runs

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-03 13:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("workflow_type", sa.String(length=60), nullable=False),
        sa.Column("business_object_type", sa.String(length=60), nullable=False),
        sa.Column("business_object_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="QUEUED", nullable=False),
        sa.Column(
            "input_ref",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "output_ref",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=120), nullable=True),
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
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name=op.f("ck_workflow_runs_status"),
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR finished_at IS NULL OR finished_at >= started_at",
            name=op.f("ck_workflow_runs_time_order"),
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name=op.f("fk_workflow_runs_requested_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_workflow_runs_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_runs")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_workflow_runs_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_workflow_runs_tenant_idempotency",
        ),
    )
    op.create_index(
        "ix_workflow_runs_tenant_object",
        "workflow_runs",
        ["tenant_id", "workflow_type", "business_object_type", "business_object_id"],
        unique=False,
    )
    op.create_index(
        "ix_workflow_runs_tenant_status_created",
        "workflow_runs",
        ["tenant_id", "status", "created_at"],
        unique=False,
    )

    op.execute("ALTER TABLE workflow_runs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE workflow_runs FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON workflow_runs "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid) "
        "WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_tenant_status_created", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_tenant_object", table_name="workflow_runs")
    op.drop_table("workflow_runs")
