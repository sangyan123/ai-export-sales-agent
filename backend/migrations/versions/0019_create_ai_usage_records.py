"""create ai usage records

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-05 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_records",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("workflow_run_id", sa.UUID(), nullable=True),
        sa.Column("operation_type", sa.String(length=40), nullable=False),
        sa.Column("model_id", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completion_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="SUCCESS", nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("requested_by_id", sa.UUID(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            "operation_type IN ('INQUIRY_PARSE', 'EMAIL_GENERATE')",
            name=op.f("ck_ai_usage_records_operation_type"),
        ),
        sa.CheckConstraint(
            "status IN ('SUCCESS', 'FAILED')",
            name=op.f("ck_ai_usage_records_status"),
        ),
        sa.CheckConstraint("prompt_tokens >= 0", name=op.f("ck_ai_usage_records_prompt_tokens_non_negative")),
        sa.CheckConstraint(
            "completion_tokens >= 0", name=op.f("ck_ai_usage_records_completion_tokens_non_negative")
        ),
        sa.CheckConstraint("total_tokens >= 0", name=op.f("ck_ai_usage_records_total_tokens_non_negative")),
        sa.CheckConstraint("duration_ms >= 0", name=op.f("ck_ai_usage_records_duration_ms_non_negative")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_ai_usage_records_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workflow_run_id"],
            ["workflow_runs.tenant_id", "workflow_runs.id"],
            name="fk_ai_usage_records_tenant_workflow_run",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"],
            ["users.id"],
            name=op.f("fk_ai_usage_records_requested_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_usage_records")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_ai_usage_records_tenant_id_id"),
    )
    op.create_index(
        "ix_ai_usage_records_tenant_created",
        "ai_usage_records",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_ai_usage_records_tenant_operation",
        "ai_usage_records",
        ["tenant_id", "operation_type", "created_at"],
    )

    op.execute("ALTER TABLE ai_usage_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ai_usage_records FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON ai_usage_records "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid) "
        "WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.drop_index("ix_ai_usage_records_tenant_operation", table_name="ai_usage_records")
    op.drop_index("ix_ai_usage_records_tenant_created", table_name="ai_usage_records")
    op.drop_table("ai_usage_records")
