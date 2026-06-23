from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.health import dependency_health


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

