import uuid
from datetime import UTC, datetime

from app.models import RagTrace, RagTraceStep
from app.traces import trace_response


def test_trace_response_orders_steps_and_defaults_json_fields() -> None:
    trace = RagTrace(
        id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        tenant_id="local-development",
        user_id="local-user",
        original_question="How do I enroll?",
        normalized_query="How do I enroll?",
        mode="generated_answer",
        evidence_status="answered",
        answer="Use the enrollment form [E1].",
        citations=["E1"],
        cache_event="miss",
        created_at=datetime(2026, 6, 23, tzinfo=UTC),
    )
    trace.steps = [
        RagTraceStep(
            trace_id=trace.id,
            sequence=1,
            stage="query analysis",
            status="completed",
            message="Analyzed query.",
            duration_ms=2,
            details={"intent": "factual_lookup"},
        )
    ]

    response = trace_response(trace)

    assert response.trace_id == trace.id
    assert response.query_analysis == {}
    assert response.selected_chunks == []
    assert response.steps[0].stage == "query analysis"
    assert response.steps[0].details == {"intent": "factual_lookup"}
