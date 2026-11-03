"""create product matches

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-03 14:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_matches",
        sa.Column("requirement_id", sa.UUID(), nullable=False),
        sa.Column("inquiry_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("score", sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column("match_status", sa.String(length=20), nullable=False),
        sa.Column(
            "matched_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "conflict_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "unknown_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("explanation", sa.Text(), nullable=True),
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
            "match_status IN ('EXACT', 'POSSIBLE', 'CONFLICT', 'NO_MATCH')",
            name=op.f("ck_product_matches_match_status"),
        ),
        sa.CheckConstraint(
            "score >= 0 AND score <= 1",
            name=op.f("ck_product_matches_score_range"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inquiry_id"],
            ["inquiries.tenant_id", "inquiries.id"],
            name=op.f("fk_product_matches_tenant_inquiry"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name=op.f("fk_product_matches_tenant_product"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requirement_id"],
            ["inquiry_requirements.tenant_id", "inquiry_requirements.id"],
            name=op.f("fk_product_matches_tenant_requirement"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_product_matches_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_matches")),
        sa.UniqueConstraint("tenant_id", "id", name="uq_product_matches_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "inquiry_id",
            "product_id",
            name="uq_product_matches_tenant_inquiry_product",
        ),
    )
    op.create_index(
        "ix_product_matches_tenant_inquiry_score",
        "product_matches",
        ["tenant_id", "inquiry_id", "score"],
        unique=False,
    )

    op.execute("ALTER TABLE product_matches ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE product_matches FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON product_matches "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid) "
        "WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.drop_index("ix_product_matches_tenant_inquiry_score", table_name="product_matches")
    op.drop_table("product_matches")
