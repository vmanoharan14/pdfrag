"""Add human evidence feedback.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evidence_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tenant_id",
            sa.String(length=100),
            server_default="local-development",
            nullable=False,
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=100), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(length=50), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("final_rank", sa.Integer(), nullable=False),
        sa.Column("dense_rank", sa.Integer(), nullable=True),
        sa.Column("sparse_rank", sa.Integer(), nullable=True),
        sa.Column("fused_score", sa.String(length=100), nullable=True),
        sa.Column("dense_score", sa.String(length=100), nullable=True),
        sa.Column("sparse_score", sa.String(length=100), nullable=True),
        sa.Column("rerank_score", sa.String(length=100), nullable=True),
        sa.Column("trace", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_feedback_tenant_id", "evidence_feedback", ["tenant_id"])
    op.create_index("ix_evidence_feedback_chunk_id", "evidence_feedback", ["chunk_id"])
    op.create_index("ix_evidence_feedback_document_id", "evidence_feedback", ["document_id"])
    op.create_index(
        "ix_evidence_feedback_document_version_id",
        "evidence_feedback",
        ["document_version_id"],
    )
    op.create_index("ix_evidence_feedback_label", "evidence_feedback", ["label"])


def downgrade() -> None:
    op.drop_index("ix_evidence_feedback_label", table_name="evidence_feedback")
    op.drop_index(
        "ix_evidence_feedback_document_version_id",
        table_name="evidence_feedback",
    )
    op.drop_index("ix_evidence_feedback_document_id", table_name="evidence_feedback")
    op.drop_index("ix_evidence_feedback_chunk_id", table_name="evidence_feedback")
    op.drop_index("ix_evidence_feedback_tenant_id", table_name="evidence_feedback")
    op.drop_table("evidence_feedback")
