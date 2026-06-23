from dataclasses import dataclass


@dataclass(frozen=True)
class QueryAnalysis:
    original_query: str
    retrieval_query: str
    intent: str
    topics: list[str]
    expansions: list[str]


TOPIC_RESULT_TERMS: dict[str, tuple[str, ...]] = {
    "mental_health": (
        "mental health",
        "behavioral health",
        "substance-related",
        "substance related",
        "psychiatric",
        "psychotherapy",
        "counseling",
        "crisis stabilization",
    ),
    "emergency_care": (
        "emergency health care",
        "medical emergency",
        "emergency services",
        "urgent care",
    ),
    "enrollment": (
        "how to enroll",
        "enrollment",
        "eligible for coverage",
        "open enrollment",
        "special enrollment",
    ),
}


TOPIC_EXPANSIONS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "mental_health": (
        (
            "anxious",
            "anxiety",
            "panic",
            "panic attack",
            "depression",
            "depressed",
            "mental",
            "therapy",
            "therapist",
            "counseling",
            "counselling",
            "behavioral",
            "psychiatric",
            "psychiatry",
        ),
        (
            "mental health benefits",
            "behavioral health services",
            "outpatient mental health",
            "inpatient mental health",
            "psychotherapy counseling services",
            "psychiatric emergency crisis services",
        ),
    ),
    "emergency_care": (
        (
            "emergency",
            "urgent",
            "crisis",
            "attack",
            "severe",
            "cannot breathe",
            "chest pain",
        ),
        (
            "emergency services",
            "emergency room",
            "urgent care",
            "medical emergency coverage",
        ),
    ),
    "enrollment": (
        (
            "enroll",
            "enrollment",
            "sign up",
            "join",
            "eligible",
            "eligibility",
        ),
        (
            "how to enroll",
            "enrollment form",
            "open enrollment period",
            "special enrollment",
            "eligibility for coverage",
        ),
    ),
}


def detect_intent(query: str) -> str:
    normalized = query.lower()
    if any(term in normalized for term in ("cover", "coverage", "benefit", "copay", "pay")):
        return "coverage_question"
    if any(term in normalized for term in ("enroll", "sign up", "join")):
        return "enrollment_question"
    return "general_question"


def analyze_query(query: str) -> QueryAnalysis:
    normalized = query.lower()
    topics: list[str] = []
    expansions: list[str] = []

    for topic, (triggers, topic_expansions) in TOPIC_EXPANSIONS.items():
        if any(trigger in normalized for trigger in triggers):
            topics.append(topic)
            expansions.extend(topic_expansions)

    deduped_expansions = list(dict.fromkeys(expansions))
    retrieval_query = "\n".join([query, *deduped_expansions])
    return QueryAnalysis(
        original_query=query,
        retrieval_query=retrieval_query,
        intent=detect_intent(query),
        topics=topics,
        expansions=deduped_expansions,
    )


def score_payload_for_query_analysis(
    payload: dict,
    analysis: QueryAnalysis,
) -> float:
    section_title = str(payload.get("section_title") or "").lower()
    text = str(payload.get("text") or "").lower()
    combined = f"{section_title}\n{text[:1200]}"
    score = 0.0

    if "table of contents" in section_title:
        score -= 4.0

    for topic in analysis.topics:
        section_weight = 4.0
        text_weight = 1.0
        if topic == "emergency_care" and "mental_health" in analysis.topics:
            section_weight = 1.5
            text_weight = 0.5
        for term in TOPIC_RESULT_TERMS.get(topic, ()):
            if term in section_title:
                score += section_weight
                break
        for term in TOPIC_RESULT_TERMS.get(topic, ()):
            if term in combined:
                score += text_weight
                break

    return score
