from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.retrieval import RetrievalRequest, RetrievalResponse, search_documents

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=RetrievalResponse)
async def chat(
    request: RetrievalRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RetrievalResponse:
    return await search_documents(request, session)
