"""create contacts and followup tasks

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-03 17:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contacts",
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("job_title", sa.String(length=120), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
            "email IS NULL OR email ~* '^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$'",
            name=op.f("ck_contacts_email_format"),
        ),
        sa.CheckConstraint(
            "language IS NULL OR language ~ '^[a-z]{2}(-[A-Za-z]{2})?$'",
            name=op.f("ck_contacts_language_format"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name=op.f("fk_contacts_tenant_customer"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_contacts_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contacts")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_contacts_tenant_id_id"),
    )
    op.create_index(
        "ix_contacts_tenant_customer",
        "contacts",
        ["tenant_id", "customer_id"],
        unique=False,
    )
    op.create_index(
        "uq_contacts_tenant_customer_primary",
        "contacts",
        ["tenant_id", "customer_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )

    op.create_table(
        "followup_tasks",
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("inquiry_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assigned_to", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("source", sa.String(length=20), server_default="MANUAL", nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('PENDING', 'DONE', 'CANCELLED')",
            name=op.f("ck_followup_tasks_status"),
        ),
        sa.CheckConstraint(
            "source IN ('MANUAL', 'RULE')",
            name=op.f("ck_followup_tasks_source"),
        ),
        sa.CheckConstraint(
            "status <> 'DONE' OR completed_at IS NOT NULL",
            name=op.f("ck_followup_tasks_completed_at_required"),
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to"],
            ["users.id"],
            name=op.f("fk_followup_tasks_assigned_to_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name=op.f("fk_followup_tasks_tenant_customer"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inquiry_id"],
            ["inquiries.tenant_id", "inquiries.id"],
            name=op.f("fk_followup_tasks_tenant_inquiry"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_followup_tasks_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_followup_tasks")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_followup_tasks_tenant_id_id"),
    )
    op.create_index(
        "ix_followup_tasks_tenant_status_due",
        "followup_tasks",
        ["tenant_id", "status", "due_at"],
        unique=False,
    )
    op.create_index(
        "ix_followup_tasks_tenant_customer_due",
        "followup_tasks",
        ["tenant_id", "customer_id", "due_at"],
        unique=False,
    )
    op.create_index(
        "ix_followup_tasks_tenant_assignee_status",
        "followup_tasks",
        ["tenant_id", "assigned_to", "status", "due_at"],
        unique=False,
    )

    for table in ("contacts", "followup_tasks"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid) "
            "WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
        )


def downgrade() -> None:
    op.drop_index(
        "ix_followup_tasks_tenant_assignee_status",
        table_name="followup_tasks",
    )
    op.drop_index(
        "ix_followup_tasks_tenant_customer_due",
        table_name="followup_tasks",
    )
    op.drop_index(
        "ix_followup_tasks_tenant_status_due",
        table_name="followup_tasks",
    )
    op.drop_table("followup_tasks")

    op.drop_index("uq_contacts_tenant_customer_primary", table_name="contacts")
    op.drop_index("ix_contacts_tenant_customer", table_name="contacts")
    op.drop_table("contacts")
