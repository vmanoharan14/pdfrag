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
from app.context_packing import PackedContext, pack_context
from app.database import get_session
from app.generation import GenerationResult, generate_answer
from app.indexing import collection_name_for, embed_texts_adaptive
from app.models import Document, DocumentChunk, DocumentVersion, EvidenceFeedback
from app.reranking import RerankItem, score_pairs
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
    rerank_score: float | None = None
    final_rank: int


class ContextBlockResponse(BaseModel):
    citation_id: str
    chunk_id: str
    source_filename: str | None
    chunk_index: int | None
    section_title: str | None
    page_number: int | None
    text: str
    char_count: int
    token_estimate: int


class PackedContextResponse(BaseModel):
    blocks: list[ContextBlockResponse]
    prompt_context: str
    char_count: int
    token_estimate: int
    max_chars: int
    truncated: bool


class AnswerResponse(BaseModel):
    text: str
    model: str
    citation_ids: list[str]
    prompt_chars: int
    prompt_token_estimate: int


class RetrievalResponse(BaseModel):
    query: str
    mode: str
    stages: list[RetrievalStage]
    results: list[RetrievalResult]
    packed_context: PackedContextResponse
    answer: AnswerResponse


class EvidenceFeedbackRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    mode: str = Field(min_length=1, max_length=100)
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    label: str = Field(pattern="^(correct|incomplete|wrong)$")
    note: str | None = Field(default=None, max_length=2000)
    final_rank: int = Field(ge=1)
    dense_rank: int | None = Field(default=None, ge=1)
    sparse_rank: int | None = Field(default=None, ge=1)
    fused_score: float | None = None
    dense_score: float | None = None
    sparse_score: float | None = None
    rerank_score: float | None = None
    trace: dict[str, Any] | None = None


class EvidenceFeedbackResponse(BaseModel):
    id: uuid.UUID
    status: str


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
    rerank_score: float | None = None
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
        rerank_score=candidate.rerank_score,
        final_rank=0,
    )


def score_to_text(score: float | None) -> str | None:
    if score is None:
        return None
    return str(score)


def packed_context_response(context: PackedContext) -> PackedContextResponse:
    return PackedContextResponse(
        blocks=[
            ContextBlockResponse(
                citation_id=block.citation_id,
                chunk_id=block.chunk_id,
                source_filename=block.source_filename,
                chunk_index=block.chunk_index,
                section_title=block.section_title,
                page_number=block.page_number,
                text=block.text,
                char_count=block.char_count,
                token_estimate=block.token_estimate,
            )
            for block in context.blocks
        ],
        prompt_context=context.prompt_context,
        char_count=context.char_count,
        token_estimate=context.token_estimate,
        max_chars=context.max_chars,
        truncated=context.truncated,
    )


def answer_response(answer: GenerationResult) -> AnswerResponse:
    return AnswerResponse(
        text=answer.answer,
        model=answer.model,
        citation_ids=answer.citation_ids,
        prompt_chars=answer.prompt_chars,
        prompt_token_estimate=answer.prompt_token_estimate,
    )


async def rerank_candidates(
    query: str,
    candidates: list[FusedCandidate],
    settings: Settings,
) -> list[FusedCandidate]:
    scores = await score_pairs(
        query,
        [
            RerankItem(
                chunk_id=candidate.chunk_id,
                text=str(candidate.payload.get("text") or ""),
            )
            for candidate in candidates
        ],
        settings,
    )
    scores_by_chunk = {score.chunk_id: score.score for score in scores}
    for candidate in candidates:
        candidate.rerank_score = scores_by_chunk.get(candidate.chunk_id)

    return sorted(
        candidates,
        key=lambda item: (
            item.rerank_score if item.rerank_score is not None else float("-inf"),
            item.fused_score,
        ),
        reverse=True,
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

    started_at = time.perf_counter()
    reranker_status = "completed"
    reranker_message = "Reranked fused candidates with the local MiniLM cross-encoder."
    try:
        ranked = await rerank_candidates(query, fused, settings)
        reranker_details = {
            "model": settings.reranker_model,
            "candidate_count": len(fused),
            "reranked_count": len(ranked),
            "best_score": ranked[0].rerank_score if ranked else None,
        }
    except Exception as exc:
        ranked = fused
        reranker_status = "failed"
        reranker_message = "Reranker failed; returned RRF order as fallback."
        reranker_details = {
            "model": settings.reranker_model,
            "candidate_count": len(fused),
            "error": str(exc),
        }
    stages.append(
        RetrievalStage(
            sequence=5,
            stage="rerank",
            status=reranker_status,
            message=reranker_message,
            duration_ms=elapsed_ms(started_at),
            details=reranker_details,
        )
    )

    stages.append(
        RetrievalStage(
            sequence=6,
            stage="context packing",
            status="completed",
            message="Packed selected evidence into the context that Qwen will receive next.",
            duration_ms=0,
            details={},
        )
    )

    started_at = time.perf_counter()
    packed_context = pack_context(
        ranked,
        max_chars=settings.context_max_chars,
        max_chunks=settings.context_max_chunks,
    )
    stages[-1].duration_ms = elapsed_ms(started_at)
    stages[-1].details = {
        "selected_chunks": len(packed_context.blocks),
        "char_count": packed_context.char_count,
        "token_estimate": packed_context.token_estimate,
        "max_chars": packed_context.max_chars,
        "truncated": packed_context.truncated,
    }

    stages.append(
        RetrievalStage(
            sequence=7,
            stage="answer generation",
            status="completed",
            message="Generated a grounded answer from packed evidence with Qwen.",
            duration_ms=0,
            details={},
        )
    )
    started_at = time.perf_counter()
    generation_status = "completed"
    generation_message = "Generated a grounded answer from packed evidence with Qwen."
    try:
        generated_answer = await generate_answer(query, packed_context, settings)
        generation_details = {
            "model": generated_answer.model,
            "prompt_chars": generated_answer.prompt_chars,
            "prompt_token_estimate": generated_answer.prompt_token_estimate,
            "citation_ids": generated_answer.citation_ids,
        }
    except httpx.HTTPError as exc:
        generation_status = "failed"
        generation_message = "Generation failed; returned a safe fallback answer."
        generated_answer = GenerationResult(
            answer="Not enough evidence.",
            model=settings.generation_model,
            prompt="",
            citation_ids=[],
            prompt_chars=0,
            prompt_token_estimate=0,
        )
        generation_details = {
            "model": settings.generation_model,
            "error": str(exc),
        }
    stages[-1].status = generation_status
    stages[-1].message = generation_message
    stages[-1].duration_ms = elapsed_ms(started_at)
    stages[-1].details = generation_details

    stages.append(
        RetrievalStage(
            sequence=8,
            stage="evidence preview",
            status="completed",
            message="Returned answer, top evidence chunks, and packed context.",
            duration_ms=0,
            details={"returned": len(ranked), "limit": FUSED_LIMIT},
        )
    )

    results = [result_from_candidate(candidate) for candidate in ranked]
    for rank, result in enumerate(results, start=1):
        result.final_rank = rank

    return RetrievalResponse(
        query=query,
        mode="generated_answer",
        stages=stages,
        results=results,
        packed_context=packed_context_response(packed_context),
        answer=answer_response(generated_answer),
    )


@router.post("/feedback", response_model=EvidenceFeedbackResponse, status_code=201)
async def record_evidence_feedback(
    request: EvidenceFeedbackRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EvidenceFeedbackResponse:
    statement = (
        select(DocumentChunk)
        .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
        .where(
            DocumentChunk.id == request.chunk_id,
            DocumentChunk.document_version_id == request.document_version_id,
            DocumentVersion.document_id == request.document_id,
            DocumentVersion.status == "active",
        )
    )
    chunk = await session.scalar(statement)
    if chunk is None:
        raise HTTPException(status_code=404, detail="Active evidence chunk not found.")

    feedback = EvidenceFeedback(
        tenant_id="local-development",
        query=request.query.strip(),
        mode=request.mode,
        chunk_id=request.chunk_id,
        document_id=request.document_id,
        document_version_id=request.document_version_id,
        label=request.label,
        note=request.note.strip() if request.note else None,
        final_rank=request.final_rank,
        dense_rank=request.dense_rank,
        sparse_rank=request.sparse_rank,
        fused_score=score_to_text(request.fused_score),
        dense_score=score_to_text(request.dense_score),
        sparse_score=score_to_text(request.sparse_score),
        rerank_score=score_to_text(request.rerank_score),
        trace=request.trace,
    )
    session.add(feedback)
    await session.commit()
    await session.refresh(feedback)

    return EvidenceFeedbackResponse(id=feedback.id, status="recorded")
