#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import sys
import urllib.error
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from run_golden_queries import GOLDEN_CASES, GoldenResult, result_to_json, run_case


@dataclass(frozen=True)
class ModelRun:
    model: str
    phase: str
    iteration: int
    results: list[GoldenResult]


def int_average(values: list[int]) -> int | None:
    if not values:
        return None
    return int(statistics.fmean(values))


def percentile_95(values: list[int]) -> int | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return int(statistics.quantiles(values, n=20, method="inclusive")[18])


def summarize_measured(model: str, runs: list[ModelRun]) -> dict[str, Any]:
    measured_results = [
        result
        for run in runs
        if run.model == model and run.phase == "measured"
        for result in run.results
    ]
    elapsed_values = [result.elapsed_ms for result in measured_results]
    generation_values = [
        result.answer_generation_ms
        for result in measured_results
        if result.answer_generation_ms is not None
    ]
    passed = sum(1 for result in measured_results if result.passed)
    total = len(measured_results)

    return {
        "model": model,
        "passed": passed,
        "total": total,
        "pass_rate": passed / total if total else None,
        "elapsed_avg_ms": int_average(elapsed_values),
        "elapsed_p95_ms": percentile_95(elapsed_values),
        "answer_generation_avg_ms": int_average(generation_values),
        "answer_generation_p95_ms": percentile_95(generation_values),
    }


def print_summary(summaries: list[dict[str, Any]]) -> None:
    print("\nMeasured summary")
    print("model | pass | avg elapsed | p95 elapsed | avg generation | p95 generation")
    print("-" * 78)
    for summary in summaries:
        passed = f"{summary['passed']}/{summary['total']}"
        elapsed_avg = summary["elapsed_avg_ms"]
        elapsed_p95 = summary["elapsed_p95_ms"]
        generation_avg = summary["answer_generation_avg_ms"]
        generation_p95 = summary["answer_generation_p95_ms"]
        print(
            f"{summary['model']} | {passed} | "
            f"{elapsed_avg if elapsed_avg is not None else '-'} ms | "
            f"{elapsed_p95 if elapsed_p95 is not None else '-'} ms | "
            f"{generation_avg if generation_avg is not None else '-'} ms | "
            f"{generation_p95 if generation_p95 is not None else '-'} ms"
        )


def write_json_report(
    path: Path,
    *,
    backend_url: str,
    models: list[str],
    warmup_runs: int,
    measured_runs: int,
    runs: list[ModelRun],
    summaries: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "backend_url": backend_url,
        "models": models,
        "warmup_runs": warmup_runs,
        "measured_runs": measured_runs,
        "summaries": summaries,
        "runs": [
            {
                "model": run.model,
                "phase": run.phase,
                "iteration": run.iteration,
                "results": [result_to_json(result) for result in run.results],
            }
            for run in runs
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_models(value: str) -> list[str]:
    models = [model.strip() for model in value.split(",") if model.strip()]
    if not models:
        raise argparse.ArgumentTypeError("at least one model is required")
    return models


def main() -> int:
    parser = argparse.ArgumentParser(
        description=("Compare generation models with separate warmup and measured golden runs.")
    )
    parser.add_argument("--backend-url", default="http://127.0.0.1:18000")
    parser.add_argument(
        "--models",
        type=parse_models,
        default=parse_models("qwen3.5:9b,gemma2:2b"),
        help="Comma-separated Ollama model names.",
    )
    parser.add_argument(
        "--case",
        choices=[case.name for case in GOLDEN_CASES],
        help="Run only one golden case by name.",
    )
    parser.add_argument("--warmup-runs", type=int, default=1)
    parser.add_argument("--measured-runs", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=120)
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Optional path to write a structured JSON report.",
    )
    args = parser.parse_args()

    if args.warmup_runs < 0:
        parser.error("--warmup-runs must be >= 0")
    if args.measured_runs < 1:
        parser.error("--measured-runs must be >= 1")

    cases = (
        tuple(case for case in GOLDEN_CASES if case.name == args.case)
        if args.case
        else GOLDEN_CASES
    )
    runs: list[ModelRun] = []

    try:
        for model in args.models:
            for phase, iterations in (
                ("warmup", args.warmup_runs),
                ("measured", args.measured_runs),
            ):
                for iteration in range(1, iterations + 1):
                    print(f"\n{phase.upper()} model={model} iteration={iteration}")
                    results = [
                        run_case(
                            case,
                            backend_url=args.backend_url,
                            generation_model=model,
                            timeout_seconds=args.timeout_seconds,
                        )
                        for case in cases
                    ]
                    runs.append(
                        ModelRun(
                            model=model,
                            phase=phase,
                            iteration=iteration,
                            results=results,
                        )
                    )
    except urllib.error.URLError as exc:
        print(f"ERROR could not call backend: {exc}", file=sys.stderr)
        return 2

    summaries = [summarize_measured(model, runs) for model in args.models]
    print_summary(summaries)

    if args.json_output:
        write_json_report(
            args.json_output,
            backend_url=args.backend_url,
            models=args.models,
            warmup_runs=args.warmup_runs,
            measured_runs=args.measured_runs,
            runs=runs,
            summaries=summaries,
        )
        print(f"wrote JSON report: {args.json_output}")

    return 0 if all(summary["passed"] == summary["total"] for summary in summaries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
