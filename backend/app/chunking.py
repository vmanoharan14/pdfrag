import re
from dataclasses import dataclass

MAX_CHUNK_CHARS = 1800
OVERLAP_CHARS = 220
KV_LINE_RATIO = 0.6  # fraction of lines that must look like "Key: value" to call it a form


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
    text = re.sub(r"^#{1,6}\s+", "", line.strip()).strip()
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    return text.strip()


def is_table_block(block: str) -> bool:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if len(lines) < 2:
        return False

    pipe_lines = [line for line in lines if line.startswith("|") and line.endswith("|")]
    if len(pipe_lines) < 2:
        return False

    return any(set(line.replace("|", "").strip()) <= {"-", ":", " "} for line in pipe_lines)


def is_form_block(block: str) -> bool:
    """Return True when the majority of lines look like key: value pairs."""
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    kv_pattern = re.compile(r"^\*{0,2}[\w][\w\s/()-]{1,60}\*{0,2}:\s+\S")
    kv_count = sum(1 for line in lines if kv_pattern.match(line))
    return kv_count / len(lines) >= KV_LINE_RATIO


def _classify_block(content: str) -> str:
    if is_table_block(content):
        return "table"
    if is_form_block(content):
        return "form"
    return "prose"


def normalize_table_markdown(block: str) -> str:
    """Compact docling's wide markdown tables.

    Docling pads every cell to match its widest content, producing separator
    rows with hundreds of dashes and data rows with trailing spaces.  This
    crushes the cross-encoder's token budget before it reaches the actual values.
    We strip cell padding and collapse separator rows to `---`.
    """
    lines = block.splitlines()
    normalized: list[str] = []
    for line in lines:
        if not line.startswith("|"):
            normalized.append(line)
            continue
        raw_cells = line.split("|")
        # split produces ['', cell, cell, ..., ''] — drop empty outer elements
        cells = [c.strip() for c in raw_cells[1:-1]] if len(raw_cells) >= 3 else [line]
        is_separator = all(
            set(c.replace("-", "").replace(":", "").replace(" ", "")) == set()
            for c in cells
        )
        if is_separator:
            normalized.append("| " + " | ".join(["---"] * len(cells)) + " |")
        else:
            normalized.append("| " + " | ".join(cells) + " |")
    return "\n".join(normalized)


def split_large_table(block: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split an oversized markdown table by row groups, repeating the header on each part."""
    if len(block) <= max_chars:
        return [block]

    lines = block.splitlines()
    separator_idx: int | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("|") and set(stripped.replace("|", "").strip()) <= {"-", ":", " "}:
            separator_idx = i
            break

    if separator_idx is None or separator_idx + 1 >= len(lines):
        return [block]

    header = "\n".join(lines[: separator_idx + 1])
    data_rows = lines[separator_idx + 1 :]

    parts: list[str] = []
    current_rows: list[str] = []
    current_len = len(header)

    for row in data_rows:
        row_len = len(row) + 1  # +1 for the newline
        if current_rows and current_len + row_len > max_chars:
            parts.append(header + "\n" + "\n".join(current_rows))
            current_rows = [row]
            current_len = len(header) + row_len
        else:
            current_rows.append(row)
            current_len += row_len

    if current_rows:
        parts.append(header + "\n" + "\n".join(current_rows))

    return parts or [block]


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
            blocks.append((current_section, _classify_block(content), content))
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


def _context_prefix(section_title: str | None) -> str:
    return f"{section_title}\n\n" if section_title else ""


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

    def emit_structured(section_title: str | None, element_type: str, block: str) -> None:
        """Emit one or more chunks for a table or form block."""
        prefix = _context_prefix(section_title)
        if element_type == "table":
            block = normalize_table_markdown(block)
        parts = split_large_table(block) if element_type == "table" else [block]
        for i, part in enumerate(parts):
            content = prefix + part
            candidates.append(
                ChunkCandidate(
                    chunk_index=len(candidates),
                    content=content,
                    token_estimate=estimate_tokens(content),
                    section_title=section_title,
                    element_type=element_type,
                    metadata={
                        "chunker": "markdown-layout-v1",
                        "characters": len(content),
                        "overlap_chars": 0,
                        "part_index": i,
                        "part_total": len(parts),
                    },
                )
            )

    for section_title, element_type, block in blockify_markdown(markdown):
        if element_type in ("table", "form"):
            flush_prose()
            emit_structured(section_title, element_type, block)
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
