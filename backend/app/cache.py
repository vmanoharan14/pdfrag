import uuid
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_session
from app.models import ResponseCache

router = APIRouter(prefix="/api/cache", tags=["cache"])

SEMANTIC_CACHE_COLLECTION = "pdfrag_response_cache_v1"
SEMANTIC_SIMILARITY_THRESHOLD = 0.93
VECTOR_SIZE = 768


def _point_id(cache_key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, cache_key))


def _qdrant_headers(settings: Settings) -> dict[str, str]:
    return {"api-key": settings.qdrant_api_key}


async def ensure_semantic_cache_collection(settings: Settings) -> None:
    headers = _qdrant_headers(settings)
    async with httpx.AsyncClient(timeout=10) as client:
        check = await client.get(
            f"{settings.qdrant_url}/collections/{SEMANTIC_CACHE_COLLECTION}",
            headers=headers,
        )
        if check.status_code == 200:
            return
        await client.put(
            f"{settings.qdrant_url}/collections/{SEMANTIC_CACHE_COLLECTION}",
            headers=headers,
            json={"vectors": {"size": VECTOR_SIZE, "distance": "Cosine"}},
        )


async def semantic_cache_lookup(
    query_embedding: list[float],
    settings: Settings,
) -> str | None:
    """Search Qdrant for a semantically similar cached query. Returns cache_key or None."""
    headers = _qdrant_headers(settings)
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{settings.qdrant_url}/collections/{SEMANTIC_CACHE_COLLECTION}/points/query",
            headers=headers,
            json={
                "query": query_embedding,
                "limit": 1,
                "score_threshold": SEMANTIC_SIMILARITY_THRESHOLD,
                "with_payload": True,
            },
        )
    if response.status_code != 200:
        return None
    points = response.json().get("result", {}).get("points", [])
    if not points:
        return None
    return points[0]["payload"].get("cache_key")


async def write_semantic_cache_entry(
    cache_key: str,
    query: str,
    query_embedding: list[float],
    settings: Settings,
) -> None:
    """Upsert query embedding into Qdrant semantic cache collection."""
    headers = _qdrant_headers(settings)
    async with httpx.AsyncClient(timeout=10) as client:
        await client.put(
            f"{settings.qdrant_url}/collections/{SEMANTIC_CACHE_COLLECTION}/points",
            headers=headers,
            json={
                "points": [
                    {
                        "id": _point_id(cache_key),
                        "vector": query_embedding,
                        "payload": {
                            "cache_key": cache_key,
                            "tenant_id": "local-development",
                            "query": query,
                        },
                    }
                ]
            },
        )


async def clear_semantic_cache(settings: Settings) -> int:
    """Delete all points from the Qdrant semantic cache collection. Returns deleted count."""
    headers = _qdrant_headers(settings)
    async with httpx.AsyncClient(timeout=10) as client:
        count_resp = await client.post(
            f"{settings.qdrant_url}/collections/{SEMANTIC_CACHE_COLLECTION}/points/count",
            headers=headers,
            json={"exact": True},
        )
        count = count_resp.json().get("result", {}).get("count", 0) if count_resp.status_code == 200 else 0

        await client.post(
            f"{settings.qdrant_url}/collections/{SEMANTIC_CACHE_COLLECTION}/points/delete",
            headers=headers,
            json={"filter": {"must": [{"key": "tenant_id", "match": {"value": "local-development"}}]}},
        )
    return count


@router.get("")
async def cache_stats(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    count = await session.scalar(select(func.count()).select_from(ResponseCache))
    hits = await session.scalar(select(func.sum(ResponseCache.hit_count)).select_from(ResponseCache))

    headers = _qdrant_headers(settings)
    semantic_count = 0
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.post(
            f"{settings.qdrant_url}/collections/{SEMANTIC_CACHE_COLLECTION}/points/count",
            headers=headers,
            json={"exact": True},
        )
        if resp.status_code == 200:
            semantic_count = resp.json().get("result", {}).get("count", 0)

    return {
        "entries": count or 0,
        "total_hits": int(hits or 0),
        "semantic_entries": semantic_count,
    }


@router.delete("")
async def clear_cache(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    result = await session.execute(delete(ResponseCache))
    await session.commit()
    semantic_deleted = await clear_semantic_cache(settings)
    return {"deleted": result.rowcount, "semantic_deleted": semantic_deleted}
