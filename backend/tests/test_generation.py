from app.context_packing import ContextBlock, PackedContext
from app.generation import (
    answer_is_cited,
    build_answer_prompt,
    build_system_prompt,
    extract_citation_ids,
)


def packed_context() -> PackedContext:
    return PackedContext(
        blocks=[
            ContextBlock(
                citation_id="E1",
                chunk_id="chunk-1",
                source_filename="benefits.pdf",
                chunk_index=10,
                section_title="How To Enroll",
                page_number=None,
                text="You may enroll by completing an enrollment form.",
                char_count=48,
                token_estimate=12,
            )
        ],
        prompt_context="[E1] benefits.pdf | section: How To Enroll | chunk: 10\n"
        "You may enroll by completing an enrollment form.",
        char_count=110,
        token_estimate=27,
        max_chars=6000,
        truncated=False,
    )


def test_build_answer_prompt_requires_evidence_and_citations() -> None:
    prompt = build_answer_prompt("how to enroll", packed_context())

    assert "Answer directly using only the evidence" in prompt
    assert "Include citation markers like [E1]" in prompt
    assert "/no_think" in prompt
    assert "how to enroll" in prompt
    assert "[E1] benefits.pdf" in prompt
    assert "Use only the provided evidence" in build_system_prompt()


def test_extract_citation_ids_preserves_order_and_deduplicates() -> None:
    assert extract_citation_ids("Use the form [E2], then submit it [E1] [E2].") == [
        "E2",
        "E1",
    ]


def test_answer_is_cited_accepts_safe_fallback() -> None:
    assert answer_is_cited("Not enough evidence.")
    assert answer_is_cited("Complete the form. [E1]")
    assert not answer_is_cited("Complete the form.")
