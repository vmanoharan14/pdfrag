from io import BytesIO

import pytest
from app.documents import latest_step_details, safe_filename, validate_upload
from fastapi import HTTPException, UploadFile


class FakeTraceStep:
    def __init__(self, sequence: int, stage: str, details: dict | None) -> None:
        self.sequence = sequence
        self.stage = stage
        self.details = details


def test_safe_filename_removes_paths_and_unsafe_characters() -> None:
    assert safe_filename("../../Quarterly Benefits (Final).pdf") == (
        "Quarterly-Benefits-Final-.pdf"
    )


def test_validate_upload_accepts_markdown_suffix() -> None:
    upload = UploadFile(
        filename="notes.md",
        file=BytesIO(b"# Notes"),
        headers={"content-type": "application/octet-stream"},
    )

    filename, media_type = validate_upload(upload)

    assert filename == "notes.md"
    assert media_type == "application/octet-stream"


def test_validate_upload_rejects_unsupported_file() -> None:
    upload = UploadFile(
        filename="archive.zip",
        file=BytesIO(b"not-a-real-zip"),
        headers={"content-type": "application/zip"},
    )

    with pytest.raises(HTTPException) as exc:
        validate_upload(upload)

    assert exc.value.status_code == 415


def test_latest_step_details_returns_most_recent_stage_details() -> None:
    steps = [
        FakeTraceStep(1, "parse", {"characters": 10}),
        FakeTraceStep(2, "chunk", {"chunk_count": 1}),
        FakeTraceStep(3, "parse", {"characters": 20}),
    ]

    assert latest_step_details(steps, "parse") == {"characters": 20}
