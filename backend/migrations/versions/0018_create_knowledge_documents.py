"""create knowledge documents

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-05 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=40), server_default="OTHER", nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("parse_status", sa.String(length=20), server_default="UPLOADED", nullable=False),
        sa.Column("uploaded_by_id", sa.UUID(), nullable=True),
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
            "source IN ('CATALOG', 'PRICE_LIST', 'CERTIFICATE', 'SPEC_SHEET', 'OTHER')",
            name=op.f("ck_knowledge_documents_source_category"),
        ),
        sa.CheckConstraint(
            "parse_status IN ('UPLOADED', 'PARSED', 'FAILED')",
            name=op.f("ck_knowledge_documents_parse_status"),
        ),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_knowledge_documents_size_bytes_non_negative")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_knowledge_documents_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"],
            ["users.id"],
            name=op.f("fk_knowledge_documents_uploaded_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_documents")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_knowledge_documents_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "object_key", name="uq_knowledge_documents_tenant_object"),
    )
    op.create_index(
        "ix_knowledge_documents_tenant_source",
        "knowledge_documents",
        ["tenant_id", "source"],
    )
    op.create_index(
        "ix_knowledge_documents_tenant_created",
        "knowledge_documents",
        ["tenant_id", "created_at"],
    )

    op.execute("ALTER TABLE knowledge_documents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE knowledge_documents FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON knowledge_documents "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid) "
        "WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_documents_tenant_created", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_tenant_source", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
