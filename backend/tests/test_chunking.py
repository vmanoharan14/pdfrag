from app.chunking import MAX_CHUNK_CHARS, chunk_markdown


def test_chunk_markdown_tracks_heading_context() -> None:
    chunks = chunk_markdown("# Benefits\n\nSpecialist copay is $40.")

    assert len(chunks) == 1
    assert chunks[0].section_title == "Benefits"
    assert chunks[0].element_type == "prose"
    assert chunks[0].content == "Specialist copay is $40."


def test_chunk_markdown_keeps_tables_together() -> None:
    markdown = """
# Rates

| Plan | Copay |
| --- | --- |
| PPO | $40 |
""".strip()

    chunks = chunk_markdown(markdown)

    assert chunks[-1].element_type == "table"
    assert "| PPO | $40 |" in chunks[-1].content


def test_chunk_markdown_packs_prose_within_section() -> None:
    markdown = "# Benefits\n\nFirst paragraph.\n\nSecond paragraph."

    chunks = chunk_markdown(markdown)

    assert len(chunks) == 1
    assert chunks[0].content == "First paragraph.\n\nSecond paragraph."


def test_chunk_markdown_splits_long_prose() -> None:
    markdown = "# Long\n\n" + "word " * (MAX_CHUNK_CHARS // 2)

    chunks = chunk_markdown(markdown)

    assert len(chunks) > 2
    assert all(chunk.token_estimate > 0 for chunk in chunks)
