import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_session
from app.models import RagEvaluation, RagTrace

router = APIRouter(prefix="/api/traces", tags=["traces"])


class TraceStepResponse(BaseModel):
    sequence: int
    stage: str
    status: str
    message: str
    duration_ms: int
    details: dict[str, Any] | None


class TraceResponse(BaseModel):
    trace_id: uuid.UUID
    tenant_id: str
    user_id: str
    original_question: str
    normalized_query: str
    mode: str
    evidence_status: str
    answer: str
    citations: list[Any]
    query_analysis: dict[str, Any]
    selected_chunks: list[Any]
    packed_context: dict[str, Any]
    timings_ms: dict[str, int]
    cache_event: str
    model_details: dict[str, Any]
    created_at: datetime
    steps: list[TraceStepResponse]


class TraceSummaryResponse(BaseModel):
    trace_id: uuid.UUID
    original_question: str
    mode: str
    evidence_status: str
    cache_event: str
    generation_model: str | None
    total_latency_ms: int
    created_at: datetime


def trace_summary(trace: RagTrace) -> TraceSummaryResponse:
    total_ms = sum((trace.timings_ms or {}).values())
    model = (trace.model_details or {}).get("generation_model")
    return TraceSummaryResponse(
        trace_id=trace.id,
        original_question=trace.original_question,
        mode=trace.mode,
        evidence_status=trace.evidence_status,
        cache_event=trace.cache_event,
        generation_model=model,
        total_latency_ms=int(total_ms),
        created_at=trace.created_at,
    )


@router.get("", response_model=list[TraceSummaryResponse])
async def list_traces(
    session: Annotated[AsyncSession, Depends(get_session)],
    q: str | None = Query(default=None),
    evidence_status: str | None = Query(default=None),
    cache_event: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[TraceSummaryResponse]:
    stmt = (
        select(RagTrace)
        .where(RagTrace.tenant_id == "local-development")
        .order_by(desc(RagTrace.created_at))
        .limit(limit)
        .offset(offset)
    )
    if q:
        stmt = stmt.where(RagTrace.original_question.ilike(f"%{q}%"))
    if evidence_status:
        stmt = stmt.where(RagTrace.evidence_status == evidence_status)
    if cache_event:
        stmt = stmt.where(RagTrace.cache_event == cache_event)

    rows = await session.scalars(stmt)
    return [trace_summary(t) for t in rows]


def trace_response(trace: RagTrace) -> TraceResponse:
    return TraceResponse(
        trace_id=trace.id,
        tenant_id=trace.tenant_id,
        user_id=trace.user_id,
        original_question=trace.original_question,
        normalized_query=trace.normalized_query,
        mode=trace.mode,
        evidence_status=trace.evidence_status,
        answer=trace.answer,
        citations=trace.citations or [],
        query_analysis=trace.query_analysis or {},
        selected_chunks=trace.selected_chunks or [],
        packed_context=trace.packed_context or {},
        timings_ms=trace.timings_ms or {},
        cache_event=trace.cache_event,
        model_details=trace.model_details or {},
        created_at=trace.created_at,
        steps=[
            TraceStepResponse(
                sequence=step.sequence,
                stage=step.stage,
                status=step.status,
                message=step.message,
                duration_ms=step.duration_ms,
                details=step.details,
            )
            for step in trace.steps
        ],
    )


class EvalResponse(BaseModel):
    trace_id: uuid.UUID
    evaluator_model: str
    ragas_version: str
    faithfulness: float | None
    answer_relevancy: float | None
    context_precision: float | None
    scores_raw: dict[str, Any] | None
    evaluated_at: datetime


@router.get("/{trace_id}/eval", response_model=EvalResponse)
async def get_trace_eval(
    trace_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EvalResponse:
    row = await session.scalar(
        select(RagEvaluation).where(RagEvaluation.trace_id == trace_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="No evaluation for this trace.")
    return EvalResponse(
        trace_id=row.trace_id,
        evaluator_model=row.evaluator_model,
        ragas_version=row.ragas_version,
        faithfulness=row.faithfulness,
        answer_relevancy=row.answer_relevancy,
        context_precision=row.context_precision,
        scores_raw=row.scores_raw,
        evaluated_at=row.evaluated_at,
    )


@router.get("/{trace_id}", response_model=TraceResponse)
async def get_trace(
    trace_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TraceResponse:
    statement = (
        select(RagTrace)
        .options(selectinload(RagTrace.steps))
        .where(RagTrace.id == trace_id, RagTrace.tenant_id == "local-development")
    )
    trace = await session.scalar(statement)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found.")

    return trace_response(trace)
