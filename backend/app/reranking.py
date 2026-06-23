import asyncio
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from app.config import Settings

RERANK_BATCH_SIZE = 8


@dataclass(frozen=True)
class RerankItem:
    chunk_id: str
    text: str


@dataclass(frozen=True)
class RerankScore:
    chunk_id: str
    score: float


def resolve_cache_dir(cache_dir: str) -> str:
    path = Path(cache_dir)
    if path.is_absolute():
        return str(path)

    candidate = Path.cwd() / path
    if candidate.exists():
        return str(candidate)

    repo_root_candidate = Path.cwd().parent / path
    return str(repo_root_candidate)


@lru_cache(maxsize=2)
def load_reranker(model_name: str, cache_dir: str, local_files_only: bool):
    resolved_cache_dir = resolve_cache_dir(cache_dir)
    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        cache_dir=resolved_cache_dir,
        local_files_only=local_files_only,
    )
    model = AutoModelForSequenceClassification.from_pretrained(
        model_name,
        cache_dir=resolved_cache_dir,
        local_files_only=local_files_only,
    )
    model.to("cpu")
    model.eval()
    return tokenizer, model


def score_pairs_sync(
    query: str,
    items: list[RerankItem],
    settings: Settings,
) -> list[RerankScore]:
    if not items:
        return []

    tokenizer, model = load_reranker(
        settings.reranker_model,
        settings.reranker_cache_dir,
        settings.reranker_local_files_only,
    )
    scores: list[RerankScore] = []

    with torch.inference_mode():
        for start in range(0, len(items), RERANK_BATCH_SIZE):
            batch = items[start : start + RERANK_BATCH_SIZE]
            encoded = tokenizer(
                [(query, item.text) for item in batch],
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            )
            outputs = model(**encoded)
            logits = outputs.logits.squeeze(dim=-1).detach().cpu().tolist()
            if isinstance(logits, float):
                logits = [logits]
            scores.extend(
                RerankScore(chunk_id=item.chunk_id, score=float(score))
                for item, score in zip(batch, logits, strict=True)
            )

    return scores


async def score_pairs(
    query: str,
    items: list[RerankItem],
    settings: Settings,
) -> list[RerankScore]:
    return await asyncio.to_thread(score_pairs_sync, query, items, settings)
