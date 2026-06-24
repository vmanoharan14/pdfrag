import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_session
from app.generation import extract_citation_ids, stream_answer_tokens
from app.retrieval import PipelineContext, RetrievalRequest, RetrievalStage, persist_stream_trace, result_from_candidate, run_pipeline_to_context

router = APIRouter(prefix="/api", tags=["chat"])



def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _stream_chat(
    request: RetrievalRequest,
    session: AsyncSession,
    settings: Settings,
) -> AsyncIterator[str]:
    # Stream each pipeline stage as it completes via a queue + background task.
    stage_queue: asyncio.Queue[RetrievalStage | None] = asyncio.Queue()

    async def on_stage(stage: RetrievalStage) -> None:
        await stage_queue.put(stage)

    async def run_and_signal() -> PipelineContext:
        result = await run_pipeline_to_context(request, session, on_stage=on_stage)
        await stage_queue.put(None)  # sentinel — pipeline finished
        return result

    pipeline_task: asyncio.Task[PipelineContext] = asyncio.create_task(run_and_signal())

    while True:
        item = await stage_queue.get()
        if item is None:
            break
        yield _sse("stage", item.model_dump())

    pipeline_result = await pipeline_task

    yield _sse("context", {
        "blocks": [
            {
                "citation_id": b.citation_id,
                "source_filename": b.source_filename,
                "chunk_index": b.chunk_index,
                "section_title": b.section_title,
                "page_number": b.page_number,
                "text": b.text,
            }
            for b in pipeline_result.packed_context.blocks
        ],
        "token_estimate": pipeline_result.packed_context.token_estimate,
        "char_count": pipeline_result.packed_context.char_count,
        "max_chars": pipeline_result.packed_context.max_chars,
        "truncated": pipeline_result.packed_context.truncated,
    })

    # Stream generation tokens.
    accumulated = ""
    async for token in stream_answer_tokens(
        request.query,
        pipeline_result.packed_context,
        settings,
        generation_model=request.generation_model,
    ):
        accumulated += token
        yield _sse("token", {"text": token})

    # Post-process the full answer (same cleanup as non-streaming path).
    if extract_citation_ids(accumulated):
        accumulated = re.sub(
            r"\s*\bNot enough evidence\.?\s*$", "", accumulated, flags=re.IGNORECASE
        ).strip()
    if not accumulated:
        accumulated = "Not enough evidence."

    citation_ids = extract_citation_ids(accumulated)
    ranked_sorted = sorted(pipeline_result.ranked, key=lambda c: c.rerank_score or 0, reverse=True)
    results_dicts = []
    for i, candidate in enumerate(ranked_sorted):
        d = result_from_candidate(candidate).model_dump()
        d["final_rank"] = i + 1
        results_dicts.append(d)
    yield _sse("done", {
        "trace_id": str(pipeline_result.trace_id),
        "answer": accumulated,
        "citation_ids": citation_ids,
        "generation_model": request.generation_model or settings.generation_model,
        "retrieval_mode": pipeline_result.retrieval_mode,
        "results": results_dicts,
    })

    await persist_stream_trace(
        session,
        pipeline=pipeline_result,
        answer=accumulated,
        citation_ids=citation_ids,
    )


@router.post("/chat/stream")
async def chat_stream(
    request: RetrievalRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    return StreamingResponse(
        _stream_chat(request, session, settings),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
