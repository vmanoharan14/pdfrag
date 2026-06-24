#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GoldenCase:
    name: str
    query: str
    expected_any_sections: tuple[str, ...] = ()
    expected_any_answer_terms: tuple[str, ...] = ()
    expected_any_topics: tuple[str, ...] = ()
    require_not_enough_evidence: bool = False
    max_table_of_contents_selected: int = 0


GOLDEN_CASES: tuple[GoldenCase, ...] = (
    GoldenCase(
        name="enrollment",
        query="how to enroll",
        expected_any_sections=(
            "how to enroll",
            "open enrollment",
            "eligibility, enrollment",
        ),
        expected_any_answer_terms=("enrollment form", "eligible", "open enrollment"),
    ),
    GoldenCase(
        name="mental_health_panic",
        query=(
            "I feel anxious and feel like having panic attacks, "
            "what kind of coverage do I have?"
        ),
        expected_any_sections=("mental health", "behavioral health", "emergency"),
        expected_any_answer_terms=("mental", "behavioral", "not enough evidence"),
        expected_any_topics=("mental_health",),
    ),
    GoldenCase(
        name="no_evidence",
        query="what is the reimbursement policy for lunar habitat repairs?",
        require_not_enough_evidence=True,
    ),
)


def post_json(url: str, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def lower_strings(values: list[Any]) -> list[str]:
    return [str(value or "").lower() for value in values]


def selected_sections(response: dict[str, Any]) -> list[str]:
    blocks = response.get("packed_context", {}).get("blocks", [])
    if not isinstance(blocks, list):
        return []
    return lower_strings(
        [block.get("section_title") for block in blocks if isinstance(block, dict)]
    )


def selected_text(response: dict[str, Any]) -> str:
    blocks = response.get("packed_context", {}).get("blocks", [])
    if not isinstance(blocks, list):
        return ""
    return "\n".join(
        str(block.get("text") or "") for block in blocks if isinstance(block, dict)
    ).lower()


def stage_names(response: dict[str, Any]) -> list[str]:
    stages = response.get("stages", [])
    if not isinstance(stages, list):
        return []
    return [str(stage.get("stage") or "") for stage in stages if isinstance(stage, dict)]


def answer_text(response: dict[str, Any]) -> str:
    answer = response.get("answer", {})
    return str(answer.get("text") or "").lower() if isinstance(answer, dict) else ""


def answer_model(response: dict[str, Any]) -> str:
    answer = response.get("answer", {})
    return str(answer.get("model") or "") if isinstance(answer, dict) else ""


def query_topics(response: dict[str, Any]) -> list[str]:
    analysis = response.get("query_analysis", {})
    topics = analysis.get("topics", []) if isinstance(analysis, dict) else []
    return [str(topic) for topic in topics] if isinstance(topics, list) else []


def validate_case(case: GoldenCase, response: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    stages = stage_names(response)
    required_stages = (
        "query analysis",
        "security context",
        "intent routing",
        "dense retrieval",
        "sparse retrieval",
        "rank fusion",
        "candidate expansion",
        "rerank",
        "context packing",
        "answer generation",
        "evidence preview",
    )
    for stage in required_stages:
        if stage not in stages:
            failures.append(f"missing trace stage: {stage}")

    sections = selected_sections(response)
    evidence_text = selected_text(response)
    combined_evidence = "\n".join([*sections, evidence_text])
    answer = answer_text(response)

    if case.expected_any_sections and not any(
        expected in combined_evidence for expected in case.expected_any_sections
    ):
        failures.append(
            "selected evidence did not contain any expected section/text term: "
            f"{case.expected_any_sections}"
        )

    if case.expected_any_answer_terms and not any(
        expected in answer for expected in case.expected_any_answer_terms
    ):
        failures.append(
            "answer did not contain any expected term: "
            f"{case.expected_any_answer_terms}"
        )

    topics = query_topics(response)
    for topic in case.expected_any_topics:
        if topic not in topics:
            failures.append(f"missing expected query topic: {topic}")

    if case.require_not_enough_evidence and "not enough evidence" not in answer:
        failures.append("answer should have been a no-evidence response")

    toc_count = sum(1 for section in sections if "table of contents" in section)
    if toc_count > case.max_table_of_contents_selected:
        failures.append(
            f"selected too many table-of-contents chunks: {toc_count} > "
            f"{case.max_table_of_contents_selected}"
        )

    return failures


def run_case(
    case: GoldenCase,
    *,
    backend_url: str,
    generation_model: str,
    timeout_seconds: float,
) -> bool:
    started_at = time.perf_counter()
    response = post_json(
        f"{backend_url.rstrip('/')}/api/chat",
        {"query": case.query, "generation_model": generation_model},
        timeout_seconds,
    )
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    failures = validate_case(case, response)
    trace_id = response.get("trace_id", "unknown")
    model = answer_model(response)

    if failures:
        print(f"FAIL {case.name} trace={trace_id} model={model} elapsed_ms={elapsed_ms}")
        for failure in failures:
            print(f"  - {failure}")
        return False

    print(f"PASS {case.name} trace={trace_id} model={model} elapsed_ms={elapsed_ms}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run live golden RAG checks against the local backend."
    )
    parser.add_argument("--backend-url", default="http://127.0.0.1:18000")
    parser.add_argument("--generation-model", default="gemma2:2b")
    parser.add_argument(
        "--case",
        choices=[case.name for case in GOLDEN_CASES],
        help="Run only one golden case by name.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=90)
    args = parser.parse_args()

    passed = 0
    cases = (
        tuple(case for case in GOLDEN_CASES if case.name == args.case)
        if args.case
        else GOLDEN_CASES
    )
    try:
        for case in cases:
            if run_case(
                case,
                backend_url=args.backend_url,
                generation_model=args.generation_model,
                timeout_seconds=args.timeout_seconds,
            ):
                passed += 1
    except urllib.error.URLError as exc:
        print(f"ERROR could not call backend: {exc}", file=sys.stderr)
        return 2

    total = len(cases)
    print(f"\n{passed}/{total} golden checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
