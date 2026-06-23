import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_session
from app.models import RagTrace

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
