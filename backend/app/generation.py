import re
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
- Answer directly using only the evidence.
- Include citation markers like [E1] for every factual claim.
- If the evidence does not answer the question, answer exactly: Not enough evidence.
- Do not think step by step.
/no_think"""


def build_system_prompt() -> str:
    return (
        "You are a careful document question-answering assistant. "
        "Use only the provided evidence. Return concise answers with citations. "
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
