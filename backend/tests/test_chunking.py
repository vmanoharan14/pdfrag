from app.chunking import MAX_CHUNK_CHARS, chunk_markdown, is_form_block, split_large_table


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


def test_chunk_markdown_table_includes_section_context() -> None:
    markdown = """
# In-Network Coverage

| Service | Copay |
| --- | --- |
| Specialist | $40 |
""".strip()

    chunks = chunk_markdown(markdown)
    table_chunk = next(c for c in chunks if c.element_type == "table")

    assert table_chunk.section_title == "In-Network Coverage"
    assert table_chunk.content.startswith("In-Network Coverage\n\n")
    assert "| Specialist | $40 |" in table_chunk.content


def test_chunk_markdown_table_without_heading_has_no_prefix() -> None:
    markdown = "| Plan | Copay |\n| --- | --- |\n| PPO | $40 |"

    chunks = chunk_markdown(markdown)

    assert chunks[0].element_type == "table"
    assert chunks[0].content.startswith("| Plan |")
    assert chunks[0].section_title is None


def test_split_large_table_repeats_header() -> None:
    header = "| A | B |\n| --- | --- |"
    rows = [f"| row{i} | val{i} |" for i in range(40)]
    big_table = header + "\n" + "\n".join(rows)

    # Use a small max_chars so the test table is forced to split
    parts = split_large_table(big_table, max_chars=300)

    assert len(parts) > 1
    for part in parts:
        assert "| A | B |" in part
        assert "| --- | --- |" in part


def test_split_large_table_small_table_unchanged() -> None:
    block = "| A | B |\n| --- | --- |\n| x | y |"

    parts = split_large_table(block)

    assert parts == [block]


def test_chunk_markdown_large_table_splits_with_context() -> None:
    # Build a table whose total content (including prefix) exceeds MAX_CHUNK_CHARS
    col_sep = "| --- | --- | --- | --- |"
    col_names = "| Service Description | Annual Deductible | Copay After Deductible | Status |"
    header = col_names + "\n" + col_sep
    deductible = "$1,500" if True else "$3,000"
    rows = [
        f"| Specialist Visit - Category {i} | {deductible} | $40 per visit | In-Network |"
        for i in range(30)
    ]
    big_table = header + "\n" + "\n".join(rows)
    markdown = f"# Coverage Details\n\n{big_table}"

    chunks = chunk_markdown(markdown)
    table_chunks = [c for c in chunks if c.element_type == "table"]

    assert len(table_chunks) > 1
    for c in table_chunks:
        assert c.section_title == "Coverage Details"
        assert c.content.startswith("Coverage Details\n\n")
        assert "| Service Description |" in c.content  # noqa: E501


def test_is_form_block_detects_key_value() -> None:
    block = "Name: John Doe\nMember ID: 123456\nPlan Type: PPO\nGroup Number: 9876"

    assert is_form_block(block) is True


def test_is_form_block_rejects_prose() -> None:
    block = (
        "The plan covers specialist visits.\n"
        "Prior authorization may be required.\n"
        "See page 12 for details."
    )

    assert is_form_block(block) is False


def test_chunk_markdown_form_block_gets_own_chunk() -> None:
    markdown = "# Member Info\n\nName: John Doe\nMember ID: 123456\nPlan Type: PPO\nGroup: 9876"

    chunks = chunk_markdown(markdown)
    form_chunks = [c for c in chunks if c.element_type == "form"]

    assert len(form_chunks) == 1
    assert form_chunks[0].section_title == "Member Info"
    assert form_chunks[0].content.startswith("Member Info\n\n")


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
