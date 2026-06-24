"""Add response cache table.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "response_cache",
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=100), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("citation_ids", sa.JSON(), nullable=False),
        sa.Column("retrieval_mode", sa.String(length=100), nullable=False),
        sa.Column("generation_model", sa.String(length=100), nullable=False),
        sa.Column("context_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("cache_key"),
    )
    op.create_index("ix_response_cache_tenant_id", "response_cache", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_response_cache_tenant_id", table_name="response_cache")
    op.drop_table("response_cache")
