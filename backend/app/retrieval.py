import time
import uuid
from dataclasses import dataclass, field
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_session
from app.indexing import collection_name_for, embed_texts_adaptive
from app.models import Document, DocumentChunk, DocumentVersion
from app.sparse_indexing import (
    SPARSE_VECTOR_NAME,
    encode_sparse_text,
    sparse_collection_name,
)

router = APIRouter(prefix="/api/retrieval", tags=["retrieval"])

DENSE_LIMIT = 12
SPARSE_LIMIT = 12
FUSED_LIMIT = 8
RRF_K = 60


class RetrievalRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


class RetrievalStage(BaseModel):
    sequence: int
    stage: str
    status: str
    message: str
    duration_ms: int
    details: dict[str, Any] = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    chunk_id: str
    document_id: str | None
    document_version_id: str | None
    source_filename: str | None
    chunk_index: int | None
    section_title: str | None
    element_type: str | None
    page_number: int | None
    text: str
    fused_score: float
    dense_score: float | None = None
    sparse_score: float | None = None
    dense_rank: int | None = None
    sparse_rank: int | None = None


class RetrievalResponse(BaseModel):
    query: str
    mode: str
    stages: list[RetrievalStage]
    results: list[RetrievalResult]


@dataclass(frozen=True)
class RetrievedPoint:
    chunk_id: str
    score: float
    rank: int
    payload: dict[str, Any]


@dataclass
class FusedCandidate:
    chunk_id: str
    payload: dict[str, Any]
    fused_score: float = 0.0
    dense_score: float | None = None
    sparse_score: float | None = None
    dense_rank: int | None = None
    sparse_rank: int | None = None
    channels: set[str] = field(default_factory=set)


def elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


def extract_points(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result")
    if isinstance(result, dict):
        points = result.get("points", [])
    else:
        points = result or []
    return points if isinstance(points, list) else []


def parse_retrieved_points(payload: dict[str, Any]) -> list[RetrievedPoint]:
    parsed: list[RetrievedPoint] = []
    for rank, point in enumerate(extract_points(payload), start=1):
        point_payload = point.get("payload") if isinstance(point, dict) else None
        if not isinstance(point_payload, dict):
            continue
        chunk_id = point_payload.get("chunk_id")
        score = point.get("score") if isinstance(point, dict) else None
        if not isinstance(chunk_id, str) or not isinstance(score, int | float):
            continue
        parsed.append(
            RetrievedPoint(
                chunk_id=chunk_id,
                score=float(score),
                rank=rank,
                payload=point_payload,
            )
        )
    return parsed


def reciprocal_rank_fuse(
    dense_points: list[RetrievedPoint],
    sparse_points: list[RetrievedPoint],
    *,
    limit: int = FUSED_LIMIT,
    k: int = RRF_K,
) -> list[FusedCandidate]:
    candidates: dict[str, FusedCandidate] = {}

    def add_point(point: RetrievedPoint, channel: str) -> None:
        candidate = candidates.setdefault(
            point.chunk_id,
            FusedCandidate(chunk_id=point.chunk_id, payload=point.payload),
        )
        candidate.fused_score += 1 / (k + point.rank)
        candidate.channels.add(channel)
        if channel == "dense":
            candidate.dense_score = point.score
            candidate.dense_rank = point.rank
        else:
            candidate.sparse_score = point.score
            candidate.sparse_rank = point.rank

    for point in dense_points:
        add_point(point, "dense")
    for point in sparse_points:
        add_point(point, "sparse")

    return sorted(
        candidates.values(),
        key=lambda item: (
            item.fused_score,
            item.dense_score or 0.0,
            item.sparse_score or 0.0,
        ),
        reverse=True,
    )[:limit]


def payload_from_db(
    chunk: DocumentChunk,
    version: DocumentVersion,
    document: Document,
) -> dict[str, Any]:
    return {
        "tenant_id": document.tenant_id,
        "document_id": str(version.document_id),
        "document_version_id": str(version.id),
        "chunk_id": str(chunk.id),
        "chunk_index": chunk.chunk_index,
        "section_title": chunk.section_title,
        "element_type": chunk.element_type,
        "page_number": chunk.page_number,
        "source_filename": version.source_filename,
        "sha256": version.sha256,
        "parser_used": version.parser_used,
        "text": chunk.content,
    }


async def keep_active_points(
    session: AsyncSession,
    points: list[RetrievedPoint],
) -> list[RetrievedPoint]:
    if not points:
        return []

    chunk_ids: list[uuid.UUID] = []
    for point in points:
        try:
            chunk_ids.append(uuid.UUID(point.chunk_id))
        except ValueError:
            continue

    if not chunk_ids:
        return []

    statement = (
        select(DocumentChunk, DocumentVersion, Document)
        .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
        .join(Document, DocumentVersion.document_id == Document.id)
        .where(DocumentChunk.id.in_(chunk_ids), DocumentVersion.status == "active")
    )
    rows = (await session.execute(statement)).all()
    active_payloads = {
        str(chunk.id): payload_from_db(chunk, version, document)
        for chunk, version, document in rows
    }

    return [
        RetrievedPoint(
            chunk_id=point.chunk_id,
            score=point.score,
            rank=point.rank,
            payload=active_payloads[point.chunk_id],
        )
        for point in points
        if point.chunk_id in active_payloads
    ]


async def query_dense(
    query: str,
    settings: Settings,
) -> tuple[list[RetrievedPoint], dict[str, Any]]:
    embedding = (await embed_texts_adaptive([query], settings))[0]
    collection_name = collection_name_for(
        settings.dense_embedding_model,
        len(embedding),
        settings,
    )
    headers = {"api-key": settings.qdrant_api_key}
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{settings.qdrant_url}/collections/{collection_name}/points/query",
            headers=headers,
            json={
                "query": embedding,
                "limit": DENSE_LIMIT,
                "with_payload": True,
            },
        )
    if response.status_code == 404:
        return [], {
            "collection": collection_name,
            "model": settings.dense_embedding_model,
            "reason": "dense collection not found",
        }
    response.raise_for_status()
    points = parse_retrieved_points(response.json())
    return points, {
        "collection": collection_name,
        "model": settings.dense_embedding_model,
        "top_k": DENSE_LIMIT,
        "returned": len(points),
        "best_score": points[0].score if points else None,
    }


async def query_sparse(
    query: str,
    settings: Settings,
) -> tuple[list[RetrievedPoint], dict[str, Any]]:
    vector = encode_sparse_text(query)
    collection_name = sparse_collection_name(settings)
    if not vector.indices:
        return [], {
            "collection": collection_name,
            "model": settings.sparse_encoder_model,
            "reason": "query had no lexical tokens",
        }

    headers = {"api-key": settings.qdrant_api_key}
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{settings.qdrant_url}/collections/{collection_name}/points/query",
            headers=headers,
            json={
                "query": {
                    "indices": vector.indices,
                    "values": vector.values,
                },
                "using": SPARSE_VECTOR_NAME,
                "limit": SPARSE_LIMIT,
                "with_payload": True,
            },
        )
    if response.status_code == 404:
        return [], {
            "collection": collection_name,
            "model": settings.sparse_encoder_model,
            "reason": "sparse collection not found",
        }
    response.raise_for_status()
    points = parse_retrieved_points(response.json())
    return points, {
        "collection": collection_name,
        "model": settings.sparse_encoder_model,
        "top_k": SPARSE_LIMIT,
        "returned": len(points),
        "best_score": points[0].score if points else None,
    }


def result_from_candidate(candidate: FusedCandidate) -> RetrievalResult:
    payload = candidate.payload
    text = payload.get("text")
    return RetrievalResult(
        chunk_id=candidate.chunk_id,
        document_id=payload.get("document_id"),
        document_version_id=payload.get("document_version_id"),
        source_filename=payload.get("source_filename"),
        chunk_index=payload.get("chunk_index"),
        section_title=payload.get("section_title"),
        element_type=payload.get("element_type"),
        page_number=payload.get("page_number"),
        text=text if isinstance(text, str) else "",
        fused_score=round(candidate.fused_score, 6),
        dense_score=candidate.dense_score,
        sparse_score=candidate.sparse_score,
        dense_rank=candidate.dense_rank,
        sparse_rank=candidate.sparse_rank,
    )


@router.post("/search", response_model=RetrievalResponse)
async def search_documents(
    request: RetrievalRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RetrievalResponse:
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=422, detail="Query cannot be blank.")

    settings = get_settings()
    stages: list[RetrievalStage] = [
        RetrievalStage(
            sequence=1,
            stage="query received",
            status="completed",
            message="Accepted the user question for retrieval.",
            duration_ms=0,
            details={"query_length": len(query)},
        )
    ]

    try:
        started_at = time.perf_counter()
        dense_points, dense_details = await query_dense(query, settings)
        raw_dense_count = len(dense_points)
        dense_points = await keep_active_points(session, dense_points)
        dense_details["returned_after_active_filter"] = len(dense_points)
        dense_details["stale_discarded"] = raw_dense_count - len(dense_points)
        stages.append(
            RetrievalStage(
                sequence=2,
                stage="dense retrieval",
                status="completed",
                message="Retrieved semantic candidates and kept active DB chunks.",
                duration_ms=elapsed_ms(started_at),
                details=dense_details,
            )
        )

        started_at = time.perf_counter()
        sparse_points, sparse_details = await query_sparse(query, settings)
        raw_sparse_count = len(sparse_points)
        sparse_points = await keep_active_points(session, sparse_points)
        sparse_details["returned_after_active_filter"] = len(sparse_points)
        sparse_details["stale_discarded"] = raw_sparse_count - len(sparse_points)
        stages.append(
            RetrievalStage(
                sequence=3,
                stage="sparse retrieval",
                status="completed",
                message="Retrieved lexical candidates and kept active DB chunks.",
                duration_ms=elapsed_ms(started_at),
                details=sparse_details,
            )
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    started_at = time.perf_counter()
    fused = reciprocal_rank_fuse(dense_points, sparse_points)
    stages.append(
        RetrievalStage(
            sequence=4,
            stage="rank fusion",
            status="completed",
            message="Fused dense and sparse rankings using reciprocal rank fusion.",
            duration_ms=elapsed_ms(started_at),
            details={
                "dense_candidates": len(dense_points),
                "sparse_candidates": len(sparse_points),
                "fused_candidates": len(fused),
                "algorithm": f"RRF k={RRF_K}",
            },
        )
    )
    stages.append(
        RetrievalStage(
            sequence=5,
            stage="evidence preview",
            status="completed",
            message="Returned top evidence chunks. Generation is intentionally not active yet.",
            duration_ms=0,
            details={"returned": len(fused), "limit": FUSED_LIMIT},
        )
    )

    return RetrievalResponse(
        query=query,
        mode="retrieval_only",
        stages=stages,
        results=[result_from_candidate(candidate) for candidate in fused],
    )
