from app.query_analysis import analyze_query, score_payload_for_query_analysis


def test_analyze_query_expands_anxiety_and_panic_to_mental_health_terms() -> None:
    analysis = analyze_query(
        "I feel anxious and feel like having panic attacks, what coverage do I have?"
    )

    assert analysis.intent == "coverage_question"
    assert "mental_health" in analysis.topics
    assert "emergency_care" in analysis.topics
    assert "mental health benefits" in analysis.expansions
    assert "behavioral health services" in analysis.expansions
    assert "emergency services" in analysis.expansions
    assert "panic attacks" in analysis.retrieval_query
    assert "outpatient mental health" in analysis.retrieval_query


def test_analyze_query_expands_enrollment_terms() -> None:
    analysis = analyze_query("how do I enroll?")

    assert analysis.intent == "enrollment_question"
    assert analysis.topics == ["enrollment"]
    assert "enrollment form" in analysis.expansions


def test_score_payload_boosts_detected_topic_and_penalizes_table_of_contents() -> None:
    analysis = analyze_query("anxiety panic attack coverage")

    mental_health_score = score_payload_for_query_analysis(
        {
            "section_title": "Mental Health Care and Substance-Related Services",
            "text": "Services are provided by a behavioral health provider.",
        },
        analysis,
    )
    toc_score = score_payload_for_query_analysis(
        {
            "section_title": "Table of Contents",
            "text": "Mental Health Care and Substance-Related Services ........ 45",
        },
        analysis,
    )

    assert mental_health_score > 0
    assert toc_score < mental_health_score
