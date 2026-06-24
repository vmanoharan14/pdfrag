from dataclasses import dataclass

from app.ingestion_quality import build_ingestion_quality, summarize_chunk_quality


@dataclass(frozen=True)
class FakeChunk:
    content: str
    element_type: str


def test_summarize_chunk_quality_counts_tables_and_sizes() -> None:
    summary = summarize_chunk_quality(
        [
            FakeChunk("A short benefits paragraph.", "prose"),
            FakeChunk("| Plan | Copay |\n| --- | --- |\n| PPO | $5 |", "table"),
        ]
    )

    assert summary.chunk_count == 2
    assert summary.table_detected_count == 1
    assert summary.total_chunk_chars > 0
    assert summary.average_chunk_chars is not None
    assert summary.max_chunk_chars is not None


def test_build_ingestion_quality_is_good_without_warnings() -> None:
    quality = build_ingestion_quality(
        parser_used="native-text",
        page_count=None,
        job_status="completed",
        current_stage="ingestion_complete",
        parse_details={"characters": 2000, "lines": 30},
        chunk_count=3,
        total_chunk_chars=1800,
        average_chunk_chars=600,
        max_chunk_chars=800,
        table_detected_count=0,
    )

    assert quality["status"] == "good"
    assert quality["warnings"] == []
    assert quality["source"] == "observability_only"


def test_build_ingestion_quality_flags_possible_ocr_and_tables() -> None:
    quality = build_ingestion_quality(
        parser_used="docling",
        page_count=5,
        job_status="completed",
        current_stage="ingestion_complete",
        parse_details={
            "characters": 300,
            "empty_page_count": 2,
            "ocr_enabled": False,
        },
        chunk_count=2,
        total_chunk_chars=280,
        average_chunk_chars=140,
        max_chunk_chars=180,
        table_detected_count=1,
    )

    assert quality["status"] == "review"
    assert quality["ocr_needed"] is True
    assert quality["characters_per_page"] == 60
    assert len(quality["warnings"]) == 3


def test_build_ingestion_quality_pending_does_not_warn_before_chunks() -> None:
    quality = build_ingestion_quality(
        parser_used=None,
        page_count=None,
        job_status="queued",
        current_stage="upload_complete",
    )

    assert quality["status"] == "pending"
    assert quality["warnings"] == []
