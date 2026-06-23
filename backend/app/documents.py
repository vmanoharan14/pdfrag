import hashlib
import re
import tempfile
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_session
from app.models import Document, DocumentVersion, IngestionJob
from app.parsing import process_document
from app.storage import ObjectStorage, get_object_storage

router = APIRouter(prefix="/api", tags=["documents"])

SUPPORTED_MEDIA_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
}
SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md", ".markdown"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


class UploadResponse(BaseModel):
    document_id: uuid.UUID
    version_id: uuid.UUID
    job_id: uuid.UUID
    filename: str
    size_bytes: int
    sha256: str
    status: str


class TraceStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence: int
    stage: str
    status: str
    message: str | None
    details: dict | None
    duration_ms: int | None


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_version_id: uuid.UUID
    status: str
    current_stage: str
    failure_reason: str | None
    steps: list[TraceStepResponse]


class DocumentListItem(BaseModel):
    document_id: uuid.UUID
    version_id: uuid.UUID
    job_id: uuid.UUID
    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    status: str
    current_stage: str
    parser_used: str | None
    page_count: int | None
    steps: list[TraceStepResponse]


def safe_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).name).strip("-")
    return cleaned or "document"


def validate_upload(file: UploadFile) -> tuple[str, str]:
    filename = safe_filename(file.filename or "document")
    suffix = Path(filename).suffix.lower()
    media_type = file.content_type or "application/octet-stream"
    if media_type not in SUPPORTED_MEDIA_TYPES and suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF, Markdown, and plain-text files are supported in this slice.",
        )
    return filename, media_type


@router.post("/documents", response_model=UploadResponse, status_code=202)
async def upload_document(
    file: Annotated[UploadFile, File()],
    session: Annotated[AsyncSession, Depends(get_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> UploadResponse:
    filename, media_type = validate_upload(file)
    document_id = uuid.uuid4()
    version_id = uuid.uuid4()
    job_id = uuid.uuid4()
    hasher = hashlib.sha256()
    size_bytes = 0

    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as buffered:
        while chunk := await file.read(1024 * 1024):
            size_bytes += len(chunk)
            if size_bytes > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Files larger than 50 MB are not supported in this slice.",
                )
            hasher.update(chunk)
            buffered.write(chunk)

        if size_bytes == 0:
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")

        digest = hasher.hexdigest()
        object_key = f"local-development/{document_id}/{version_id}/original/{filename}"
        buffered.seek(0)
        await storage.upload(buffered, object_key, media_type)

    document = Document(
        id=document_id,
        tenant_id="local-development",
        display_name=filename,
    )
    version = DocumentVersion(
        id=version_id,
        document=document,
        source_filename=filename,
        media_type=media_type,
        size_bytes=size_bytes,
        sha256=digest,
        object_key=object_key,
        status="uploaded",
    )
    job = IngestionJob(
        id=job_id,
        document_version=version,
        status="queued",
        current_stage="upload_complete",
    )
    session.add(document)

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        await storage.delete(object_key)
        raise

    process_document.send(str(job_id))

    return UploadResponse(
        document_id=document_id,
        version_id=version_id,
        job_id=job_id,
        filename=filename,
        size_bytes=size_bytes,
        sha256=digest,
        status=job.status,
    )


@router.get("/ingestion-jobs/{job_id}", response_model=JobResponse)
async def get_ingestion_job(
    job_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IngestionJob:
    statement = (
        select(IngestionJob)
        .options(selectinload(IngestionJob.steps))
        .where(IngestionJob.id == job_id)
    )
    job = await session.scalar(statement)
    if job is None:
        raise HTTPException(status_code=404, detail="Ingestion job not found.")
    return job


@router.post("/ingestion-jobs/{job_id}/retry", response_model=JobResponse, status_code=202)
async def retry_ingestion_job(
    job_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IngestionJob:
    statement = (
        select(IngestionJob)
        .options(selectinload(IngestionJob.steps))
        .where(IngestionJob.id == job_id)
    )
    job = await session.scalar(statement)
    if job is None:
        raise HTTPException(status_code=404, detail="Ingestion job not found.")
    if job.status == "processing":
        raise HTTPException(status_code=409, detail="Ingestion job is already processing.")

    job.status = "queued"
    job.current_stage = "queued"
    job.failure_reason = None
    await session.commit()
    process_document.send(str(job_id))
    return job


@router.get("/documents", response_model=list[DocumentListItem])
async def list_documents(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DocumentListItem]:
    statement = (
        select(DocumentVersion)
        .options(
            selectinload(DocumentVersion.document),
            selectinload(DocumentVersion.ingestion_jobs).selectinload(
                IngestionJob.steps
            ),
        )
        .order_by(DocumentVersion.created_at.desc())
    )
    versions = (await session.scalars(statement)).all()
    result: list[DocumentListItem] = []
    for version in versions:
        job = max(version.ingestion_jobs, key=lambda item: item.created_at)
        result.append(
            DocumentListItem(
                document_id=version.document_id,
                version_id=version.id,
                job_id=job.id,
                filename=version.source_filename,
                media_type=version.media_type,
                size_bytes=version.size_bytes,
                sha256=version.sha256,
                status=job.status,
                current_stage=job.current_stage,
                parser_used=version.parser_used,
                page_count=version.page_count,
                steps=[
                    TraceStepResponse.model_validate(step)
                    for step in job.steps
                ],
            )
        )
    return result
