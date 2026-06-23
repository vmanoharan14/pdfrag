"""Add sparse index metadata to chunks.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column(
            "sparse_index_status",
            sa.String(length=50),
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column(
        "document_chunks",
        sa.Column("sparse_vector_point_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("sparse_vector_collection", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("sparse_encoder_model", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("sparse_indexed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_document_chunks_sparse_vector_point_id",
        "document_chunks",
        ["sparse_vector_point_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_document_chunks_sparse_vector_point_id",
        "document_chunks",
        type_="unique",
    )
    op.drop_column("document_chunks", "sparse_indexed_at")
    op.drop_column("document_chunks", "sparse_encoder_model")
    op.drop_column("document_chunks", "sparse_vector_collection")
    op.drop_column("document_chunks", "sparse_vector_point_id")
    op.drop_column("document_chunks", "sparse_index_status")
