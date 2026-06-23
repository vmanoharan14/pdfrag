from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.documents import router as documents_router
from app.health import dependency_health
from app.retrieval import router as retrieval_router
from app.traces import router as traces_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_settings()
    yield


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:13000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(documents_router)
app.include_router(retrieval_router)
app.include_router(traces_router)


@app.get("/api/health/live")
async def live() -> dict[str, str]:
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@app.get("/api/health/ready")
async def ready() -> dict:
    return await dependency_health(settings)
