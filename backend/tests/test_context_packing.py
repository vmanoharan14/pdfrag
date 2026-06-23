from types import SimpleNamespace

from app.context_packing import pack_context


def candidate(chunk_id: str, text: str, chunk_index: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        chunk_id=chunk_id,
        payload={
            "chunk_id": chunk_id,
            "source_filename": "benefits.pdf",
            "chunk_index": chunk_index,
            "section_title": "How To Enroll",
            "page_number": None,
            "text": text,
        },
    )


def test_pack_context_assigns_citation_ids_and_preserves_metadata() -> None:
    packed = pack_context(
        [
            candidate("chunk-1", "Complete the enrollment form."),
            candidate("chunk-2", "Submit it within 31 days.", chunk_index=2),
        ],
        max_chars=1000,
        max_chunks=6,
    )

    assert [block.citation_id for block in packed.blocks] == ["E1", "E2"]
    assert packed.blocks[0].source_filename == "benefits.pdf"
    assert packed.blocks[0].section_title == "How To Enroll"
    assert "[E1] benefits.pdf | section: How To Enroll | chunk: 1" in (
        packed.prompt_context
    )
    assert "Complete the enrollment form." in packed.prompt_context
    assert packed.truncated is False


def test_pack_context_enforces_chunk_and_character_limits() -> None:
    packed = pack_context(
        [
            candidate("chunk-1", "A" * 500),
            candidate("chunk-2", "B" * 500),
        ],
        max_chars=360,
        max_chunks=1,
    )

    assert len(packed.blocks) == 1
    assert packed.char_count <= 360
    assert packed.truncated is True
