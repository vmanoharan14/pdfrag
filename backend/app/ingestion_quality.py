from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChunkQualitySummary:
    chunk_count: int
    total_chunk_chars: int
    average_chunk_chars: int | None
    max_chunk_chars: int | None
    table_detected_count: int


def summarize_chunk_quality(chunks: Sequence[Any]) -> ChunkQualitySummary:
    contents = [str(getattr(chunk, "content", "") or "") for chunk in chunks]
    chunk_count = len(contents)
    total_chunk_chars = sum(len(content) for content in contents)
    table_detected_count = sum(
        1 for chunk in chunks if str(getattr(chunk, "element_type", "")) == "table"
    )
    return ChunkQualitySummary(
        chunk_count=chunk_count,
        total_chunk_chars=total_chunk_chars,
        average_chunk_chars=(
            round(total_chunk_chars / chunk_count) if chunk_count else None
        ),
        max_chunk_chars=max((len(content) for content in contents), default=None),
        table_detected_count=table_detected_count,
    )


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_ingestion_quality(
    *,
    parser_used: str | None,
    page_count: int | None,
    job_status: str,
    current_stage: str,
    parse_details: dict[str, Any] | None = None,
    chunk_count: int = 0,
    total_chunk_chars: int | None = None,
    average_chunk_chars: int | None = None,
    max_chunk_chars: int | None = None,
    table_detected_count: int = 0,
) -> dict[str, Any]:
    """Build observability-only ingestion quality signals.

    This intentionally does not feed back into parsing, chunking, indexing, or
    retrieval. It only summarizes already-produced artifacts so the UI can show
    whether a document deserves human review before relying on its answers.
    """

    details = parse_details or {}
    character_count = _int_or_none(details.get("characters"))
    if character_count is None:
        character_count = total_chunk_chars

    details_table_count = _int_or_none(details.get("table_detected_count")) or 0
    table_count = max(table_detected_count, details_table_count)

    empty_page_count = _int_or_none(details.get("empty_page_count"))
    ocr_used = bool(details.get("ocr_enabled") or details.get("ocr_used"))

    characters_per_page = None
    if character_count is not None and page_count:
        characters_per_page = round(character_count / page_count)

    warnings: list[str] = []
    ocr_needed = False

    if job_status == "failed":
        warnings.append("Ingestion failed; quality metrics may be incomplete.")

    if chunk_count == 0 and job_status not in {"queued", "processing"}:
        warnings.append("No chunks were created, so this document cannot be retrieved.")

    if page_count and character_count is not None and characters_per_page is not None:
        if characters_per_page < 120 and not ocr_used:
            ocr_needed = True
            warnings.append(
                "Very little text was extracted per page; scanned/OCR-needed PDF is possible."
            )

    if empty_page_count and empty_page_count > 0:
        warnings.append(
            f"{empty_page_count} page(s) had no extracted text or table content."
        )

    if table_count > 0:
        warnings.append(
            "Table-like content was detected; retrieval is still text-only until "
            "table-aware retrieval lands."
        )

    if average_chunk_chars is not None and average_chunk_chars < 250 and chunk_count >= 10:
        warnings.append(
            "Average chunk size is very small; retrieval may need chunking review."
        )

    if max_chunk_chars is not None and max_chunk_chars > 2500:
        warnings.append(
            "A very large chunk was created; context packing may need chunking review."
        )

    if job_status in {"queued", "processing"} and chunk_count == 0:
        status = "pending"
    elif job_status == "failed":
        status = "failed"
    elif warnings:
        status = "review"
    else:
        status = "good"

    return {
        "status": status,
        "parser_used": parser_used,
        "page_count": page_count,
        "character_count": character_count,
        "characters_per_page": characters_per_page,
        "empty_page_count": empty_page_count,
        "chunk_count": chunk_count,
        "total_chunk_chars": total_chunk_chars,
        "average_chunk_chars": average_chunk_chars,
        "max_chunk_chars": max_chunk_chars,
        "table_detected_count": table_count,
        "ocr_used": ocr_used,
        "ocr_needed": ocr_needed,
        "warnings": warnings,
        "source": "observability_only",
        "current_stage": current_stage,
    }
