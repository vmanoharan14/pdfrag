import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings
from app.query_analysis import QueryAnalysis

SUPPORTED_RETRIEVAL_PATHS = {"hybrid", "dense", "sparse", "table", "form"}
SUPPORTED_INTENTS = {
    "general_question",
    "coverage_question",
    "enrollment_question",
    "factual_lookup",
    "table_lookup",
    "form_lookup",
    "comparison",
    "summary",
    "multi_document_question",
}


@dataclass(frozen=True)
class RouterDecision:
    source: str
    model: str
    intent: str
    requested_retrieval_path: str
    selected_retrieval_path: str
    needs_rewrite: bool
    rewrite_query: str
    fallback_reason: str | None = None


def build_router_prompt(query: str, analysis: QueryAnalysis) -> str:
    return f"""Classify this document-search question.

Return only compact JSON with these keys:
- intent: one of general_question, coverage_question, enrollment_question,
  factual_lookup, table_lookup, form_lookup, comparison, summary,
  multi_document_question
- retrieval_path: one of hybrid, dense, sparse, table, form
- needs_rewrite: boolean
- rewrite_query: string

Rules:
- Preserve names, dates, quoted text, numbers, IDs, policy codes, and dollar amounts.
- If unsure, choose hybrid.
- Do not answer the question.

Question:
{query}

Deterministic baseline:
intent={analysis.intent}
topics={", ".join(analysis.topics) or "none"}"""


def deterministic_router_decision(
    analysis: QueryAnalysis,
    *,
    model: str,
    source: str = "deterministic",
    fallback_reason: str | None = None,
) -> RouterDecision:
    return RouterDecision(
        source=source,
        model=model,
        intent=analysis.intent,
        requested_retrieval_path="hybrid",
        selected_retrieval_path="hybrid",
        needs_rewrite=bool(analysis.expansions),
        rewrite_query=analysis.retrieval_query,
        fallback_reason=fallback_reason,
    )


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if match is None:
            raise
        parsed = json.loads(match.group(0))

    if not isinstance(parsed, dict):
        raise ValueError("Router returned non-object JSON.")
    return parsed


def router_decision_from_payload(
    payload: dict[str, Any],
    analysis: QueryAnalysis,
    *,
    model: str,
) -> RouterDecision:
    intent = str(payload.get("intent") or analysis.intent)
    if intent not in SUPPORTED_INTENTS:
        intent = analysis.intent

    requested_path = str(payload.get("retrieval_path") or "hybrid")
    if requested_path not in SUPPORTED_RETRIEVAL_PATHS:
        requested_path = "hybrid"

    rewrite_query = str(payload.get("rewrite_query") or "").strip()
    if not rewrite_query:
        rewrite_query = analysis.retrieval_query

    return RouterDecision(
        source="gemma",
        model=model,
        intent=intent,
        requested_retrieval_path=requested_path,
        selected_retrieval_path="hybrid",
        needs_rewrite=bool(payload.get("needs_rewrite", False)),
        rewrite_query=rewrite_query,
    )


async def route_query(
    query: str,
    analysis: QueryAnalysis,
    settings: Settings,
) -> RouterDecision:
    if not settings.router_enabled:
        return deterministic_router_decision(
            analysis,
            model="deterministic",
            fallback_reason="router disabled for local latency",
        )

    prompt = build_router_prompt(query, analysis)
    try:
        async with httpx.AsyncClient(timeout=settings.router_timeout_seconds) as client:
            response = await client.post(
                f"{settings.ollama_base_url}/api/chat",
                json={
                    "model": settings.router_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a strict JSON router for a local RAG system. "
                                "Return JSON only. Do not answer the user."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "think": False,
                    "options": {
                        "temperature": 0,
                        "top_p": 0.1,
                        "num_ctx": 1024,
                        "num_predict": 120,
                    },
                },
            )
            response.raise_for_status()
    except (httpx.HTTPError, TimeoutError) as exc:
        return deterministic_router_decision(
            analysis,
            model=settings.router_model,
            source="deterministic_fallback",
            fallback_reason=str(exc) or exc.__class__.__name__,
        )

    try:
        content = str(response.json().get("message", {}).get("content") or "")
        return router_decision_from_payload(
            extract_json_object(content),
            analysis,
            model=settings.router_model,
        )
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        return deterministic_router_decision(
            analysis,
            model=settings.router_model,
            source="deterministic_fallback",
            fallback_reason=f"invalid router output: {exc}",
        )
