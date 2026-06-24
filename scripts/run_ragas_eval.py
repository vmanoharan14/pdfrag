#!/usr/bin/env python3
# ruff: noqa: I001  — import order is intentional: sys.modules must be patched before ragas import
"""Offline RAGAS evaluation script.

Fetches unevaluated RAG traces from the database, runs RAGAS faithfulness,
answer relevancy, and context precision metrics using a local Ollama model,
and writes scores back to the rag_evaluations table.

Usage:
    .venv/bin/python scripts/run_ragas_eval.py
    .venv/bin/python scripts/run_ragas_eval.py --model qwen3.5:9b --limit 20
    .venv/bin/python scripts/run_ragas_eval.py --trace-id <uuid>
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

# Shim for ragas 0.2.x hard-importing removed langchain_community modules
from types import ModuleType
for _path in ["langchain_community.chat_models.vertexai"]:
    if _path not in sys.modules:
        sys.modules[_path] = ModuleType(_path)
sys.modules["langchain_community.chat_models.vertexai"].ChatVertexAI = type("ChatVertexAI", (), {})
import langchain_community.llms as _llms_mod  # noqa: E402
if not hasattr(_llms_mod, "VertexAI"):
    _llms_mod.VertexAI = type("VertexAI", (), {})

# Add backend to path so app.* imports work
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import asyncio  # noqa: E402
import os  # noqa: E402

import ragas  # noqa: E402
from langchain_ollama import ChatOllama, OllamaEmbeddings  # noqa: E402
from ragas import EvaluationDataset, SingleTurnSample, evaluate  # noqa: E402
from ragas.embeddings import LangchainEmbeddingsWrapper  # noqa: E402
from ragas.llms import LangchainLLMWrapper  # noqa: E402
from ragas.metrics import (  # noqa: E402
    Faithfulness,
    LLMContextPrecisionWithoutReference,
    ResponseRelevancy,
)
from ragas.run_config import RunConfig  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models import RagEvaluation, RagTrace  # noqa: E402

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
RAGAS_VERSION = ragas.__version__

# Column names produced by the new-style metric classes
COL_FAITHFULNESS = "faithfulness"
COL_RELEVANCY = "response_relevancy"
COL_PRECISION = "llm_context_precision_without_reference"


def build_engine(settings):
    dsn = settings.postgres_dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_async_engine(dsn, pool_pre_ping=True)


def extract_contexts(trace: RagTrace) -> list[str]:
    blocks = (trace.packed_context or {}).get("blocks") or []
    return [b.get("text", "") for b in blocks if b.get("text")]


async def fetch_traces(
    session: AsyncSession,
    trace_id: uuid.UUID | None,
    limit: int,
    skip_evaluated: bool,
) -> list[RagTrace]:
    stmt = (
        select(RagTrace)
        .where(RagTrace.tenant_id == "local-development")
        .order_by(RagTrace.created_at.desc())
        .limit(limit)
    )
    if trace_id:
        stmt = select(RagTrace).where(RagTrace.id == trace_id)
    if skip_evaluated and not trace_id:
        evaluated_ids = select(RagEvaluation.trace_id)
        stmt = stmt.where(RagTrace.id.notin_(evaluated_ids))
    rows = await session.scalars(stmt)
    return list(rows)


async def upsert_evaluation(
    session: AsyncSession,
    trace_id: uuid.UUID,
    evaluator_model: str,
    scores: dict,
) -> None:
    existing = await session.scalar(
        select(RagEvaluation).where(RagEvaluation.trace_id == trace_id)
    )
    if existing:
        existing.evaluator_model = evaluator_model
        existing.ragas_version = RAGAS_VERSION
        existing.faithfulness = scores.get("faithfulness")
        existing.answer_relevancy = scores.get("answer_relevancy")
        existing.context_precision = scores.get("context_precision")
        existing.scores_raw = scores
    else:
        session.add(
            RagEvaluation(
                trace_id=trace_id,
                evaluator_model=evaluator_model,
                ragas_version=RAGAS_VERSION,
                faithfulness=scores.get("faithfulness"),
                answer_relevancy=scores.get("answer_relevancy"),
                context_precision=scores.get("context_precision"),
                scores_raw=scores,
            )
        )
    await session.commit()


def run_ragas(traces: list[RagTrace], model: str) -> dict[uuid.UUID, dict]:
    evaluable = [t for t in traces if extract_contexts(t)]
    skipped = [t for t in traces if not extract_contexts(t)]

    for t in skipped:
        print(f"  skip  {t.id}  (no context — evidence_status={t.evidence_status})")

    if not evaluable:
        return {}

    llm = LangchainLLMWrapper(
        ChatOllama(model=model, base_url=OLLAMA_BASE_URL, request_timeout=300)
    )
    embeddings = LangchainEmbeddingsWrapper(
        OllamaEmbeddings(model="nomic-embed-text", base_url=OLLAMA_BASE_URL)
    )
    run_config = RunConfig(timeout=300, max_retries=2, max_wait=120)

    samples = [
        SingleTurnSample(
            user_input=t.original_question,
            response=t.answer,
            retrieved_contexts=extract_contexts(t),
        )
        for t in evaluable
    ]
    dataset = EvaluationDataset(samples=samples)

    print(f"\nRunning RAGAS on {len(evaluable)} trace(s) with {model}…")
    result_df = evaluate(
        dataset=dataset,
        metrics=[
            Faithfulness(),
            ResponseRelevancy(),
            LLMContextPrecisionWithoutReference(),
        ],
        llm=llm,
        embeddings=embeddings,
        run_config=run_config,
        raise_exceptions=False,
    ).to_pandas()

    def _score(row, key: str) -> float | None:
        raw = row.get(key, "")
        return None if str(raw) == "nan" else float(raw or 0)

    scores_by_trace: dict[uuid.UUID, dict] = {}
    for i, trace in enumerate(evaluable):
        row = result_df.iloc[i]
        scores_by_trace[trace.id] = {
            "faithfulness": _score(row, COL_FAITHFULNESS),
            "answer_relevancy": _score(row, COL_RELEVANCY),
            "context_precision": _score(row, COL_PRECISION),
        }

    return scores_by_trace


async def main(args: argparse.Namespace) -> None:
    settings = get_settings()
    engine = build_engine(settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    trace_id = uuid.UUID(args.trace_id) if args.trace_id else None

    async with session_factory() as session:
        traces = await fetch_traces(
            session,
            trace_id=trace_id,
            limit=args.limit,
            skip_evaluated=not args.rerun,
        )

    if not traces:
        print("No unevaluated traces found. Use --rerun to re-evaluate existing scores.")
        return

    print(f"Found {len(traces)} trace(s) to evaluate.")
    scores_by_trace = run_ragas(traces, model=args.model)

    async with session_factory() as session:
        for trace in traces:
            if trace.id not in scores_by_trace:
                continue
            scores = scores_by_trace[trace.id]
            await upsert_evaluation(session, trace.id, args.model, scores)
            f = scores.get("faithfulness")
            ar = scores.get("answer_relevancy")
            cp = scores.get("context_precision")

            def _fmt(v: float | None) -> str:
                return f"{v:.3f}" if v is not None else "—"

            print(
                f"  saved {trace.id}  "
                f"faithfulness={_fmt(f)}  "
                f"relevancy={_fmt(ar)}  "
                f"precision={_fmt(cp)}"
            )

    await engine.dispose()
    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run offline RAGAS evaluation on stored traces")
    parser.add_argument("--model", default="qwen3.5:9b", help="Ollama model for evaluation")
    parser.add_argument("--limit", type=int, default=20, help="Max traces to evaluate per run")
    parser.add_argument("--trace-id", help="Evaluate a single trace by ID")
    parser.add_argument("--rerun", action="store_true", help="Re-evaluate already-scored traces")
    asyncio.run(main(parser.parse_args()))
