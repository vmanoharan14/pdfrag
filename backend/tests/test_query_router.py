from app.query_analysis import analyze_query
from app.query_router import (
    deterministic_router_decision,
    extract_json_object,
    route_query,
    router_decision_from_payload,
)


class RouterSettings:
    router_enabled = False
    router_model = "gemma2:2b"
    router_timeout_seconds = 1.5
    ollama_base_url = "http://127.0.0.1:11434"


def test_extract_json_object_accepts_fenced_json() -> None:
    payload = extract_json_object(
        """```json
{
  "intent": "coverage_question",
  "retrieval_path": "hybrid",
  "needs_rewrite": true,
  "rewrite_query": "mental health coverage"
}
```"""
    )

    assert payload["intent"] == "coverage_question"
    assert payload["retrieval_path"] == "hybrid"


def test_router_decision_sanitizes_unknown_values() -> None:
    analysis = analyze_query("how to enroll")

    decision = router_decision_from_payload(
        {
            "intent": "invented",
            "retrieval_path": "invented",
            "needs_rewrite": True,
            "rewrite_query": "enrollment form",
        },
        analysis,
        model="gemma2:2b",
    )

    assert decision.source == "gemma"
    assert decision.intent == "enrollment_question"
    assert decision.requested_retrieval_path == "hybrid"
    assert decision.selected_retrieval_path == "hybrid"
    assert decision.rewrite_query == "enrollment form"


def test_deterministic_router_fallback_preserves_analysis_query() -> None:
    analysis = analyze_query("anxiety panic attack coverage")

    decision = deterministic_router_decision(
        analysis,
        model="gemma2:2b",
        source="deterministic_fallback",
        fallback_reason="timeout",
    )

    assert decision.source == "deterministic_fallback"
    assert decision.selected_retrieval_path == "hybrid"
    assert decision.fallback_reason == "timeout"
    assert decision.rewrite_query == analysis.retrieval_query


async def test_route_query_uses_deterministic_path_when_router_disabled() -> None:
    analysis = analyze_query("how to enroll")

    decision = await route_query("how to enroll", analysis, RouterSettings())  # type: ignore[arg-type]

    assert decision.source == "deterministic"
    assert decision.model == "deterministic"
    assert decision.selected_retrieval_path == "hybrid"
    assert decision.fallback_reason == "router disabled for local latency"
