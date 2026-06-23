import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="local-development",
        index=True,
    )
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="uploaded",
        index=True,
    )
    parser_used: Mapped[str | None] = mapped_column(String(100))
    page_count: Mapped[int | None] = mapped_column(Integer)
    parsed_text_object_key: Mapped[str | None] = mapped_column(
        String(1024),
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    document: Mapped[Document] = relationship(back_populates="versions")
    ingestion_jobs: Mapped[list["IngestionJob"]] = relationship(
        back_populates="document_version",
        cascade="all, delete-orphan",
    )
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document_version",
        cascade="all, delete-orphan",
        order_by="DocumentChunk.chunk_index",
    )


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="queued",
        index=True,
    )
    current_stage: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="upload_complete",
    )
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    document_version: Mapped[DocumentVersion] = relationship(back_populates="ingestion_jobs")
    steps: Mapped[list["IngestionTraceStep"]] = relationship(
        back_populates="ingestion_job",
        cascade="all, delete-orphan",
        order_by="IngestionTraceStep.sequence",
    )


class IngestionTraceStep(Base):
    __tablename__ = "ingestion_trace_steps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    ingestion_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingestion_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    ingestion_job: Mapped[IngestionJob] = relationship(back_populates="steps")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name="uq_document_chunks_version_index",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False)
    section_title: Mapped[str | None] = mapped_column(String(512))
    element_type: Mapped[str] = mapped_column(String(50), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON)
    index_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    vector_point_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), unique=True)
    vector_collection: Mapped[str | None] = mapped_column(String(255))
    embedding_model: Mapped[str | None] = mapped_column(String(255))
    embedding_dimension: Mapped[int | None] = mapped_column(Integer)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sparse_index_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
    )
    sparse_vector_point_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        unique=True,
    )
    sparse_vector_collection: Mapped[str | None] = mapped_column(String(255))
    sparse_encoder_model: Mapped[str | None] = mapped_column(String(255))
    sparse_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    document_version: Mapped[DocumentVersion] = relationship(back_populates="chunks")
