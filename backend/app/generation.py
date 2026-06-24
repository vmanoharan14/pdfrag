import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from app.config import Settings
from app.context_packing import PackedContext

CITATION_PATTERN = re.compile(r"\[E\d+\]")


@dataclass(frozen=True)
class GenerationResult:
    answer: str
    model: str
    prompt: str
    citation_ids: list[str]
    prompt_chars: int
    prompt_token_estimate: int


def build_answer_prompt(query: str, context: PackedContext) -> str:
    return f"""Question:
{query}

Evidence:
{context.prompt_context}

Instructions:
- IMPORTANT: If the evidence does not directly answer the question, you MUST respond with only these words: Not enough evidence. Do NOT try to connect unrelated evidence to the question.
- Write a single, clear answer in plain conversational English that directly addresses the question.
- Combine all relevant evidence into one cohesive response — do not answer each evidence block separately.
- After each fact, add a citation like [E1] or [E2].
- Do not think step by step.
/no_think"""


def build_system_prompt() -> str:
    return (
        "You are a friendly insurance benefits assistant. "
        "Answer member questions in clear, plain English using only the provided evidence. "
        "Synthesize all evidence into one helpful response with inline citations like [E1]. "
        "Do not think step by step."
    )


def extract_citation_ids(answer: str) -> list[str]:
    seen: set[str] = set()
    citations: list[str] = []
    for match in CITATION_PATTERN.findall(answer):
        if match in seen:
            continue
        seen.add(match)
        citations.append(match.strip("[]"))
    return citations


def answer_is_cited(answer: str) -> bool:
    normalized = answer.strip().lower()
    if normalized == "not enough evidence." or normalized == "not enough evidence":
        return True
    return bool(extract_citation_ids(answer))


async def generate_answer(
    query: str,
    context: PackedContext,
    settings: Settings,
    generation_model: str | None = None,
) -> GenerationResult:
    selected_model = generation_model or settings.generation_model
    if not context.prompt_context.strip():
        return GenerationResult(
            answer="Not enough evidence.",
            model=selected_model,
            prompt=build_answer_prompt(query, context),
            citation_ids=[],
            prompt_chars=0,
            prompt_token_estimate=0,
        )

    prompt = build_answer_prompt(query, context)
    async with httpx.AsyncClient(timeout=settings.generation_timeout_seconds) as client:
        response = await client.post(
            f"{settings.ollama_base_url}/api/chat",
            json={
                "model": selected_model,
                "messages": [
                    {
                        "role": "system",
                        "content": build_system_prompt(),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                "stream": False,
                "think": False,
                "options": {
                    "temperature": 0,
                    "top_p": 0.2,
                    "num_ctx": 4096,
                    "num_predict": settings.generation_num_predict,
                },
            },
        )
        response.raise_for_status()

    answer = str(response.json().get("message", {}).get("content") or "").strip()
    if not answer:
        answer = "Not enough evidence."
    # Strip spurious trailing "Not enough evidence." when the answer already has citations.
    if extract_citation_ids(answer):
        answer = re.sub(r"\s*\bNot enough evidence\.?\s*$", "", answer, flags=re.IGNORECASE).strip()
    if not answer_is_cited(answer):
        answer = f"{answer}\n\nCitation check: no citation marker was returned."

    return GenerationResult(
        answer=answer,
        model=selected_model,
        prompt=prompt,
        citation_ids=extract_citation_ids(answer),
        prompt_chars=len(prompt),
        prompt_token_estimate=max(1, len(prompt) // 4),
    )


async def stream_answer_tokens(
    query: str,
    context: PackedContext,
    settings: Settings,
    generation_model: str | None = None,
) -> AsyncIterator[str]:
    """Yield raw token strings from Ollama one at a time."""
    selected_model = generation_model or settings.generation_model
    if not context.prompt_context.strip():
        yield "Not enough evidence."
        return

    prompt = build_answer_prompt(query, context)
    payload = {
        "model": selected_model,
        "messages": [
            {"role": "system", "content": build_system_prompt()},
            {"role": "user", "content": prompt},
        ],
        "stream": True,
        "think": False,
        "options": {
            "temperature": 0,
            "top_p": 0.2,
            "num_ctx": 4096,
            "num_predict": settings.generation_num_predict,
        },
    }
    async with httpx.AsyncClient(timeout=settings.generation_timeout_seconds) as client:
        async with client.stream(
            "POST",
            f"{settings.ollama_base_url}/api/chat",
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                token = chunk.get("message", {}).get("content", "")
                if token:
                    yield token
                if chunk.get("done"):
                    break
