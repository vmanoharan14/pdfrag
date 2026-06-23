import re
from dataclasses import dataclass

MAX_CHUNK_CHARS = 1800
OVERLAP_CHARS = 220


@dataclass(frozen=True)
class ChunkCandidate:
    chunk_index: int
    content: str
    token_estimate: int
    section_title: str | None
    element_type: str
    metadata: dict


def estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / 4))


def is_heading(line: str) -> bool:
    return bool(re.match(r"^#{1,6}\s+\S", line.strip()))


def heading_text(line: str) -> str:
    return re.sub(r"^#{1,6}\s+", "", line.strip()).strip()


def is_table_block(block: str) -> bool:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if len(lines) < 2:
        return False

    pipe_lines = [line for line in lines if line.startswith("|") and line.endswith("|")]
    if len(pipe_lines) < 2:
        return False

    return any(set(line.replace("|", "").strip()) <= {"-", ":", " "} for line in pipe_lines)


def split_large_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            boundary = text.rfind("\n\n", start, end)
            if boundary > start + max_chars // 2:
                end = boundary

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(0, end - OVERLAP_CHARS)

    return chunks


def blockify_markdown(markdown: str) -> list[tuple[str | None, str, str]]:
    current_section: str | None = None
    blocks: list[tuple[str | None, str, str]] = []
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        content = "\n".join(buffer).strip()
        if content:
            element_type = "table" if is_table_block(content) else "prose"
            blocks.append((current_section, element_type, content))
        buffer = []

    for line in markdown.splitlines():
        if is_heading(line):
            flush()
            current_section = heading_text(line)
            continue

        if not line.strip():
            flush()
            continue

        buffer.append(line)

    flush()
    return blocks


def chunk_markdown(markdown: str) -> list[ChunkCandidate]:
    candidates: list[ChunkCandidate] = []
    prose_buffer: list[str] = []
    prose_section: str | None = None

    def flush_prose() -> None:
        nonlocal prose_buffer, prose_section
        if not prose_buffer:
            return

        content = "\n\n".join(prose_buffer)
        for part in split_large_text(content):
            candidates.append(
                ChunkCandidate(
                    chunk_index=len(candidates),
                    content=part,
                    token_estimate=estimate_tokens(part),
                    section_title=prose_section,
                    element_type="prose",
                    metadata={
                        "chunker": "markdown-layout-v1",
                        "characters": len(part),
                        "overlap_chars": OVERLAP_CHARS,
                        "source_blocks": len(prose_buffer),
                    },
                )
            )

        prose_buffer = []
        prose_section = None

    for section_title, element_type, block in blockify_markdown(markdown):
        if element_type == "table":
            flush_prose()
            candidates.append(
                ChunkCandidate(
                    chunk_index=len(candidates),
                    content=block,
                    token_estimate=estimate_tokens(block),
                    section_title=section_title,
                    element_type="table",
                    metadata={
                        "chunker": "markdown-layout-v1",
                        "characters": len(block),
                        "overlap_chars": 0,
                    },
                )
            )
            continue

        proposed = "\n\n".join([*prose_buffer, block])
        if prose_buffer and (
            section_title != prose_section or len(proposed) > MAX_CHUNK_CHARS
        ):
            flush_prose()

        prose_section = section_title
        prose_buffer.append(block)

    flush_prose()
    return candidates
