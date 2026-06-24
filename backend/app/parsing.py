import asyncio
import json
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import dramatiq
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.broker import broker as _broker  # noqa: F401
from app.chunking import chunk_markdown
from app.database import session_factory
from app.indexing import index_chunks_dense
from app.ingestion_quality import build_ingestion_quality, summarize_chunk_quality
from app.models import DocumentChunk, DocumentVersion, IngestionJob, IngestionTraceStep
from app.sparse_indexing import index_chunks_sparse
from app.storage import get_object_storage


@dataclass(frozen=True)
class ParsedDocument:
    markdown: str
    parser_used: str
    page_count: int | None
    details: dict


async def add_trace_step(
    session: AsyncSession,
    job: IngestionJob,
    stage: str,
    status: str,
    message: str,
    *,
    details: dict | None = None,
    duration_ms: int | None = None,
) -> None:
    current_sequence = await session.scalar(
        select(func.coalesce(func.max(IngestionTraceStep.sequence), 0)).where(
            IngestionTraceStep.ingestion_job_id == job.id
        )
    )
    now = datetime.now(UTC)
    session.add(
        IngestionTraceStep(
            ingestion_job_id=job.id,
            sequence=int(current_sequence or 0) + 1,
            stage=stage,
            status=status,
            message=message,
            details=details,
            started_at=now,
            completed_at=now if status in {"completed", "failed"} else None,
            duration_ms=duration_ms,
        )
    )
    job.current_stage = stage
    await session.commit()


def parse_text(path: Path) -> ParsedDocument:
    raw = path.read_bytes()
    text: str | None = None
    encoding_used: str | None = None
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = raw.decode(encoding)
            encoding_used = encoding
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("Unable to decode text file.")

    return ParsedDocument(
        markdown=text,
        parser_used="native-text",
        page_count=None,
        details={
            "characters": len(text),
            "lines": len(text.splitlines()),
            "encoding": encoding_used,
        },
    )


def docling_page_quality_details(document: object, markdown: str) -> dict:
    pages = getattr(document, "pages", {}) or {}
    page_numbers = sorted(pages)
    page_text_chars = {page_no: 0 for page_no in page_numbers}

    for page_no in page_numbers:
        try:
            page_items = document.iterate_items(page_no=page_no, with_groups=False)  # type: ignore[attr-defined]
        except (AttributeError, TypeError):
            continue

        for item, _level in page_items:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                page_text_chars[page_no] += len(text.strip())

    table_pages: set[int] = set()
    for table in getattr(document, "tables", []) or []:
        for provenance in getattr(table, "prov", []) or []:
            page_no = getattr(provenance, "page_no", None)
            if isinstance(page_no, int):
                table_pages.add(page_no)

    empty_page_count = sum(
        1
        for page_no in page_numbers
        if page_text_chars.get(page_no, 0) == 0 and page_no not in table_pages
    )

    return {
        "characters": len(markdown),
        "pages": len(page_numbers),
        "empty_page_count": empty_page_count,
        "text_item_count": len(getattr(document, "texts", []) or []),
        "table_detected_count": len(getattr(document, "tables", []) or []),
        "form_detected_count": len(getattr(document, "form_items", []) or []),
        "key_value_detected_count": len(getattr(document, "key_value_items", []) or []),
        "picture_count": len(getattr(document, "pictures", []) or []),
        "ocr_enabled": False,
    }


def parse_pdf(path: Path) -> ParsedDocument:
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = False
    pipeline_options.do_table_structure = True
    pipeline_options.accelerator_options = AcceleratorOptions(
        num_threads=4,
        device=AcceleratorDevice.CPU,
    )
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )
    result = converter.convert(path)
    document = result.document
    markdown = document.export_to_markdown()
    details = docling_page_quality_details(document, markdown)
    return ParsedDocument(
        markdown=markdown,
        parser_used="docling",
        page_count=len(document.pages),
        details=details,
    )


async def process_ingestion(job_id: uuid.UUID) -> None:
    storage = get_object_storage()
    async with session_factory() as session:
        job = await session.get(IngestionJob, job_id)
        if job is None:
            raise ValueError(f"Ingestion job {job_id} does not exist.")
        version = await session.scalar(
            select(DocumentVersion)
            .options(selectinload(DocumentVersion.document))
            .where(DocumentVersion.id == job.document_version_id)
        )
        if version is None:
            raise ValueError(f"Document version {job.document_version_id} does not exist.")
        if job.status == "completed":
            return

        job.status = "processing"
        job.failure_reason = None
        await add_trace_step(
            session,
            job,
            "worker_started",
            "completed",
            "Dramatiq worker accepted the ingestion job.",
        )

        with tempfile.TemporaryDirectory(prefix="pdfrag-parse-") as temp_dir:
            parsed_key = (
                f"local-development/{version.document_id}/{version.id}"
                "/parsed/document.md"
            )
            metadata_key = (
                f"local-development/{version.document_id}/{version.id}"
                "/parsed/metadata.json"
            )
            if version.parsed_text_object_key:
                parsed_path = Path(temp_dir) / "parsed.md"
                started = perf_counter()
                await add_trace_step(
                    session,
                    job,
                    "parsed_artifact_download",
                    "running",
                    "Downloading existing canonical Markdown from MinIO.",
                )
                await storage.download_to_path(version.parsed_text_object_key, parsed_path)
                markdown = await asyncio.to_thread(parsed_path.read_text, encoding="utf-8")
                parsed = ParsedDocument(
                    markdown=markdown,
                    parser_used=version.parser_used or "stored-markdown",
                    page_count=version.page_count,
                    details={
                        "characters": len(markdown),
                        "reused_parsed_artifact": True,
                    },
                )
                await add_trace_step(
                    session,
                    job,
                    "parsed_artifact_download",
                    "completed",
                    "Canonical Markdown downloaded from MinIO.",
                    details={"markdown_object_key": version.parsed_text_object_key},
                    duration_ms=round((perf_counter() - started) * 1000),
                )
                await add_trace_step(
                    session,
                    job,
                    "parse",
                    "completed",
                    "Reused existing parsed Markdown artifact.",
                    details=parsed.details,
                )
            else:
                source_path = Path(temp_dir) / version.source_filename

                started = perf_counter()
                await add_trace_step(
                    session,
                    job,
                    "source_download",
                    "running",
                    "Downloading the original from MinIO.",
                )
                await storage.download_to_path(version.object_key, source_path)
                await add_trace_step(
                    session,
                    job,
                    "source_download",
                    "completed",
                    "Original downloaded from MinIO.",
                    details={"size_bytes": version.size_bytes},
                    duration_ms=round((perf_counter() - started) * 1000),
                )

                started = perf_counter()
                await add_trace_step(
                    session,
                    job,
                    "parse",
                    "running",
                    "Parsing document content.",
                )
                if source_path.suffix.lower() == ".pdf":
                    parsed = await asyncio.to_thread(parse_pdf, source_path)
                else:
                    parsed = await asyncio.to_thread(parse_text, source_path)
                await add_trace_step(
                    session,
                    job,
                    "parse",
                    "completed",
                    f"Parsed with {parsed.parser_used}.",
                    details=parsed.details,
                    duration_ms=round((perf_counter() - started) * 1000),
                )

                started = perf_counter()
                await add_trace_step(
                    session,
                    job,
                    "artifact_write",
                    "running",
                    "Writing canonical parsed artifacts to MinIO.",
                )
                await storage.upload_bytes(
                    parsed.markdown.encode("utf-8"),
                    parsed_key,
                    "text/markdown",
                )
                await storage.upload_bytes(
                    json.dumps(
                        {
                            "parser_used": parsed.parser_used,
                            "page_count": parsed.page_count,
                            **parsed.details,
                        },
                        indent=2,
                    ).encode("utf-8"),
                    metadata_key,
                    "application/json",
                )
                version.parser_used = parsed.parser_used
                version.page_count = parsed.page_count
                version.parsed_text_object_key = parsed_key
                version.status = "parsed"
                await add_trace_step(
                    session,
                    job,
                    "artifact_write",
                    "completed",
                    "Canonical Markdown and parser metadata stored in MinIO.",
                    details={
                        "markdown_object_key": parsed_key,
                        "metadata_object_key": metadata_key,
                    },
                    duration_ms=round((perf_counter() - started) * 1000),
                )

            started = perf_counter()
            await add_trace_step(
                session,
                job,
                "chunk",
                "running",
                "Creating layout-aware Markdown chunks.",
            )
            chunks = chunk_markdown(parsed.markdown)
            if not chunks:
                raise ValueError("Parsed document produced no chunks.")
            chunk_quality = summarize_chunk_quality(chunks)

            await session.execute(
                delete(DocumentChunk).where(DocumentChunk.document_version_id == version.id)
            )
            db_chunks = [
                DocumentChunk(
                    document_version_id=version.id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    token_estimate=chunk.token_estimate,
                    section_title=chunk.section_title,
                    element_type=chunk.element_type,
                    metadata_=chunk.metadata,
                )
                for chunk in chunks
            ]
            session.add_all(db_chunks)
            version.status = "chunked"
            await session.flush()
            await session.commit()
            await add_trace_step(
                session,
                job,
                "chunk",
                "completed",
                f"Created {len(chunks)} chunks.",
                details={
                    "chunk_count": len(chunks),
                    "chunker": "markdown-layout-v1",
                    "total_chunk_chars": chunk_quality.total_chunk_chars,
                    "average_chunk_chars": chunk_quality.average_chunk_chars,
                    "max_chunk_chars": chunk_quality.max_chunk_chars,
                    "table_detected_count": chunk_quality.table_detected_count,
                },
                duration_ms=round((perf_counter() - started) * 1000),
            )

            started = perf_counter()
            await add_trace_step(
                session,
                job,
                "dense_index",
                "running",
                "Embedding chunks and writing dense vectors to Qdrant.",
            )
            index_result = await index_chunks_dense(session, version, db_chunks)
            version.status = "active"
            await session.commit()
            await add_trace_step(
                session,
                job,
                "dense_index",
                "completed",
                f"Indexed {index_result.point_count} dense vectors.",
                details={
                    "collection": index_result.collection_name,
                    "embedding_model": index_result.embedding_model,
                    "embedding_dimension": index_result.embedding_dimension,
                    "point_count": index_result.point_count,
                },
                duration_ms=round((perf_counter() - started) * 1000),
            )

            started = perf_counter()
            await add_trace_step(
                session,
                job,
                "sparse_index",
                "running",
                "Encoding lexical sparse vectors and writing them to Qdrant.",
            )
            sparse_result = await index_chunks_sparse(session, version, db_chunks)
            await add_trace_step(
                session,
                job,
                "sparse_index",
                "completed",
                f"Indexed {sparse_result.point_count} sparse vectors.",
                details={
                    "collection": sparse_result.collection_name,
                    "encoder_model": sparse_result.encoder_model,
                    "point_count": sparse_result.point_count,
                },
                duration_ms=round((perf_counter() - started) * 1000),
            )

            job.status = "completed"
            await add_trace_step(
                session,
                job,
                "ingestion_complete",
                "completed",
                "Dense and sparse indexing completed. The document is ready for retrieval.",
                details={
                    "parser_used": parsed.parser_used,
                    "page_count": parsed.page_count,
                    "chunk_count": len(chunks),
                    "dense_vectors": index_result.point_count,
                    "sparse_vectors": sparse_result.point_count,
                    "quality": build_ingestion_quality(
                        parser_used=parsed.parser_used,
                        page_count=parsed.page_count,
                        job_status="completed",
                        current_stage="ingestion_complete",
                        parse_details=parsed.details,
                        chunk_count=chunk_quality.chunk_count,
                        total_chunk_chars=chunk_quality.total_chunk_chars,
                        average_chunk_chars=chunk_quality.average_chunk_chars,
                        max_chunk_chars=chunk_quality.max_chunk_chars,
                        table_detected_count=chunk_quality.table_detected_count,
                    ),
                },
            )


async def fail_ingestion(job_id: uuid.UUID, exc: Exception) -> None:
    async with session_factory() as session:
        job = await session.get(IngestionJob, job_id)
        if job is None:
            return
        job.status = "failed"
        job.failure_reason = str(exc)[:2000]
        await add_trace_step(
            session,
            job,
            job.current_stage or "unknown",
            "failed",
            "Ingestion failed.",
            details={"error": str(exc)[:2000]},
        )


@dramatiq.actor(
    queue_name="ingestion",
    max_retries=2,
    min_backoff=5000,
    max_backoff=30000,
    time_limit=600000,
)
def process_document(job_id: str) -> None:
    parsed_job_id = uuid.UUID(job_id)
    try:
        asyncio.run(process_ingestion(parsed_job_id))
    except Exception as exc:
        asyncio.run(fail_ingestion(parsed_job_id, exc))
        raise
