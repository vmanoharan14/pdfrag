from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ContextBlock:
    citation_id: str
    chunk_id: str
    source_filename: str | None
    chunk_index: int | None
    section_title: str | None
    page_number: int | None
    text: str
    char_count: int
    token_estimate: int


@dataclass(frozen=True)
class PackedContext:
    blocks: list[ContextBlock]
    prompt_context: str
    char_count: int
    token_estimate: int
    max_chars: int
    truncated: bool


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def clean_context_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines()).strip()


def source_label(payload: dict[str, Any]) -> str:
    parts = [str(payload.get("source_filename") or "Unknown source")]
    section_title = payload.get("section_title")
    page_number = payload.get("page_number")
    chunk_index = payload.get("chunk_index")

    if section_title:
        parts.append(f"section: {section_title}")
    if page_number:
        parts.append(f"page: {page_number}")
    if chunk_index is not None:
        parts.append(f"chunk: {chunk_index}")

    return " | ".join(parts)


def pack_context(
    candidates: list[Any],
    *,
    max_chars: int,
    max_chunks: int,
) -> PackedContext:
    blocks: list[ContextBlock] = []
    prompt_parts: list[str] = []
    used_chars = 0
    truncated = False
    seen_chunks: set[str] = set()

    for candidate in candidates:
        if len(blocks) >= max_chunks:
            truncated = True
            break

        payload = candidate.payload
        chunk_id = str(candidate.chunk_id)
        if chunk_id in seen_chunks:
            continue
        seen_chunks.add(chunk_id)

        text = clean_context_text(str(payload.get("text") or ""))
        if not text:
            continue

        citation_id = f"E{len(blocks) + 1}"
        header = f"[{citation_id}] {source_label(payload)}"
        entry = f"{header}\n{text}"
        projected_chars = used_chars + len(entry)
        if projected_chars > max_chars:
            remaining = max_chars - used_chars - len(header) - 2
            if remaining <= 240:
                truncated = True
                break
            text = f"{text[:remaining].rstrip()}…"
            entry = f"{header}\n{text}"
            truncated = True

        prompt_parts.append(entry)
        used_chars += len(entry)
        blocks.append(
            ContextBlock(
                citation_id=citation_id,
                chunk_id=chunk_id,
                source_filename=payload.get("source_filename"),
                chunk_index=payload.get("chunk_index"),
                section_title=payload.get("section_title"),
                page_number=payload.get("page_number"),
                text=text,
                char_count=len(text),
                token_estimate=estimate_tokens(text),
            )
        )

        if truncated:
            break

    prompt_context = "\n\n".join(prompt_parts)
    return PackedContext(
        blocks=blocks,
        prompt_context=prompt_context,
        char_count=len(prompt_context),
        token_estimate=estimate_tokens(prompt_context) if prompt_context else 0,
        max_chars=max_chars,
        truncated=truncated,
    )
