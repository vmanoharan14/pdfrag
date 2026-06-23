"""Add persisted RAG traces.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rag_traces",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id",
            sa.String(length=100),
            server_default="local-development",
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(length=100),
            server_default="local-user",
            nullable=False,
        ),
        sa.Column("original_question", sa.Text(), nullable=False),
        sa.Column("normalized_query", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=100), nullable=False),
        sa.Column("evidence_status", sa.String(length=100), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=True),
        sa.Column("query_analysis", sa.JSON(), nullable=True),
        sa.Column("selected_chunks", sa.JSON(), nullable=True),
        sa.Column("packed_context", sa.JSON(), nullable=True),
        sa.Column("timings_ms", sa.JSON(), nullable=True),
        sa.Column("cache_event", sa.String(length=100), server_default="miss", nullable=False),
        sa.Column("model_details", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rag_traces_tenant_id", "rag_traces", ["tenant_id"])
    op.create_index("ix_rag_traces_user_id", "rag_traces", ["user_id"])
    op.create_index("ix_rag_traces_created_at", "rag_traces", ["created_at"])

    op.create_table(
        "rag_trace_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trace_id"], ["rag_traces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rag_trace_steps_trace_id", "rag_trace_steps", ["trace_id"])
    op.create_index(
        "ix_rag_trace_steps_trace_sequence",
        "rag_trace_steps",
        ["trace_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_index("ix_rag_trace_steps_trace_sequence", table_name="rag_trace_steps")
    op.drop_index("ix_rag_trace_steps_trace_id", table_name="rag_trace_steps")
    op.drop_table("rag_trace_steps")
    op.drop_index("ix_rag_traces_created_at", table_name="rag_traces")
    op.drop_index("ix_rag_traces_user_id", table_name="rag_traces")
    op.drop_index("ix_rag_traces_tenant_id", table_name="rag_traces")
    op.drop_table("rag_traces")
