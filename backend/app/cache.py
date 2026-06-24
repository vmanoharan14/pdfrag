from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import ResponseCache

router = APIRouter(prefix="/api/cache", tags=["cache"])


@router.get("")
async def cache_stats(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    count = await session.scalar(select(func.count()).select_from(ResponseCache))
    hits = await session.scalar(select(func.sum(ResponseCache.hit_count)).select_from(ResponseCache))
    return {"entries": count or 0, "total_hits": int(hits or 0)}


@router.delete("")
async def clear_cache(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    result = await session.execute(delete(ResponseCache))
    await session.commit()
    return {"deleted": result.rowcount}
