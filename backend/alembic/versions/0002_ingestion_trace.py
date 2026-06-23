"""Add parsing metadata and ingestion trace steps.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_versions",
        sa.Column("parser_used", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("page_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("parsed_text_object_key", sa.String(length=1024), nullable=True),
    )
    op.create_unique_constraint(
        "uq_document_versions_parsed_text_object_key",
        "document_versions",
        ["parsed_text_object_key"],
    )
    op.create_table(
        "ingestion_trace_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ingestion_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["ingestion_job_id"],
            ["ingestion_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ingestion_trace_steps_ingestion_job_id",
        "ingestion_trace_steps",
        ["ingestion_job_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ingestion_trace_steps_ingestion_job_id",
        table_name="ingestion_trace_steps",
    )
    op.drop_table("ingestion_trace_steps")
    op.drop_constraint(
        "uq_document_versions_parsed_text_object_key",
        "document_versions",
        type_="unique",
    )
    op.drop_column("document_versions", "parsed_text_object_key")
    op.drop_column("document_versions", "page_count")
    op.drop_column("document_versions", "parser_used")
