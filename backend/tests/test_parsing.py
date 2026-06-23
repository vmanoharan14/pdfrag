from pathlib import Path

from app.parsing import parse_text


def test_parse_text_returns_canonical_content(tmp_path: Path) -> None:
    source = tmp_path / "notes.md"
    source.write_text("# Benefits\n\nSpecialist copay: $40\n", encoding="utf-8")

    parsed = parse_text(source)

    assert parsed.parser_used == "native-text"
    assert parsed.markdown.startswith("# Benefits")
    assert parsed.details["encoding"] == "utf-8"
    assert parsed.details["lines"] == 3
