import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_session
from app.generation import extract_citation_ids, stream_answer_tokens
from app.cache import semantic_cache_lookup, write_semantic_cache_entry
from app.indexing import embed_texts_adaptive
from app.models import ResponseCache
from app.retrieval import PipelineContext, RetrievalRequest, RetrievalStage, persist_stream_trace, read_response_cache, result_from_candidate, run_pipeline_to_context, write_response_cache

router = APIRouter(prefix="/api", tags=["chat"])



def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _stream_chat(
    request: RetrievalRequest,
    session: AsyncSession,
    settings: Settings,
) -> AsyncIterator[str]:
    query = request.query.strip()
    generation_model = request.generation_model or settings.generation_model

    # 1. Exact hash cache lookup (no embedding needed).
    cached, cache_key = await read_response_cache(
        session, query=query, settings=settings, generation_model=generation_model
    )

    # 2. Semantic cache lookup on exact miss — embed query and search Qdrant.
    query_embedding: list[float] | None = None
    if not cached:
        query_embedding = (await embed_texts_adaptive([query], settings))[0]
        semantic_key = await semantic_cache_lookup(query_embedding, settings)
        if semantic_key:
            cached = await session.get(ResponseCache, semantic_key)
            if cached:
                cached.hit_count += 1
                await session.commit()

    if cached:
        cache_type = "exact" if query_embedding is None else "semantic"
        yield _sse("stage", RetrievalStage(
            sequence=1, stage="query analysis", status="completed",
            message="Analyzed the question and expanded retrieval terms.",
            duration_ms=0, details={},
        ).model_dump())
        yield _sse("stage", RetrievalStage(
            sequence=2, stage="security context", status="completed",
            message="Applied fixed local development principal and tenant context.",
            duration_ms=0, details={},
        ).model_dump())
        yield _sse("stage", RetrievalStage(
            sequence=3, stage="response cache", status="completed",
            message=f"{cache_type.capitalize()} cache hit — served from cache (hit #{cached.hit_count}).",
            duration_ms=0, details={"cache_enabled": True, "cache_event": "hit", "cache_type": cache_type, "hit_count": cached.hit_count},
        ).model_dump())
        yield _sse("context", cached.context_snapshot)
        yield _sse("done", {
            "trace_id": None,
            "answer": cached.answer,
            "citation_ids": cached.citation_ids,
            "generation_model": cached.generation_model,
            "retrieval_mode": cached.retrieval_mode,
            "results": [],
            "from_cache": True,
            "cached_at": cached.created_at.isoformat(),
        })
        return

    # Cache miss — stream each pipeline stage as it completes via a queue + background task.
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
        "from_cache": False,
        "cached_at": None,
    })

    context_snapshot = {
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
    }
    await write_response_cache(
        session,
        cache_key=cache_key,
        query=query,
        answer=accumulated,
        citation_ids=citation_ids,
        retrieval_mode=pipeline_result.retrieval_mode,
        generation_model=generation_model,
        context_snapshot=context_snapshot,
    )
    # Embed query (reuse embedding if already computed during cache miss check)
    if query_embedding is None:
        query_embedding = (await embed_texts_adaptive([query], settings))[0]
    await write_semantic_cache_entry(cache_key, query, query_embedding, settings)
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
