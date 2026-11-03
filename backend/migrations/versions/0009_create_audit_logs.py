"""create audit logs

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-03 12:02:36.366638

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("tenant_id", sa.UUID(), nullable=True),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("resource_type", sa.String(length=60), nullable=False),
        sa.Column("resource_id", sa.UUID(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_audit_logs_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_audit_logs_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(
        "ix_audit_logs_tenant_action", "audit_logs", ["tenant_id", "action"], unique=False
    )
    op.create_index(
        "ix_audit_logs_tenant_created", "audit_logs", ["tenant_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_audit_logs_tenant_resource",
        "audit_logs",
        ["tenant_id", "resource_type", "resource_id"],
        unique=False,
    )

    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON audit_logs "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid) "
        "WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_tenant_resource", table_name="audit_logs")
    op.drop_index("ix_audit_logs_tenant_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_tenant_action", table_name="audit_logs")
    op.drop_table("audit_logs")
