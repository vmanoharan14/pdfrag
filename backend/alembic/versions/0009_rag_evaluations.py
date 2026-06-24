"""Add rag_evaluations table for offline RAGAS scores.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-24
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
        "rag_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evaluator_model", sa.String(length=100), nullable=False),
        sa.Column("ragas_version", sa.String(length=50), nullable=False),
        sa.Column("faithfulness", sa.Float(), nullable=True),
        sa.Column("answer_relevancy", sa.Float(), nullable=True),
        sa.Column("context_precision", sa.Float(), nullable=True),
        sa.Column("scores_raw", sa.JSON(), nullable=True),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trace_id"], ["rag_traces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trace_id", name="uq_rag_evaluations_trace_id"),
    )
    op.create_index("ix_rag_evaluations_trace_id", "rag_evaluations", ["trace_id"])


def downgrade() -> None:
    op.drop_index("ix_rag_evaluations_trace_id", table_name="rag_evaluations")
    op.drop_table("rag_evaluations")
