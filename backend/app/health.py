import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import httpx
import psycopg
import redis.asyncio as redis

from app.config import Settings


@dataclass(frozen=True)
class DependencyCheck:
    name: str
    check: Callable[[], Awaitable[dict[str, Any]]]


async def _timed_check(
    dependency: DependencyCheck,
    timeout_seconds: float,
) -> dict[str, Any]:
    started = perf_counter()
    try:
        details = await asyncio.wait_for(
            dependency.check(),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        return {
            "status": "unhealthy",
            "latency_ms": round((perf_counter() - started) * 1000, 2),
            "error": f"timed out after {timeout_seconds:.1f}s",
        }
    except Exception as exc:
        return {
            "status": "unhealthy",
            "latency_ms": round((perf_counter() - started) * 1000, 2),
            "error": str(exc),
        }

    return {
        "status": "healthy",
        "latency_ms": round((perf_counter() - started) * 1000, 2),
        **details,
    }


def build_dependency_checks(settings: Settings) -> list[DependencyCheck]:
    async def check_postgres() -> dict[str, Any]:
        async with await psycopg.AsyncConnection.connect(
            settings.postgres_dsn,
            connect_timeout=settings.dependency_timeout_seconds,
        ) as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("select version()")
                version = await cursor.fetchone()
        return {"version": version[0].split(",")[0] if version else "unknown"}

    async def check_redis() -> dict[str, Any]:
        client = redis.from_url(
            settings.redis_url,
            socket_connect_timeout=settings.dependency_timeout_seconds,
            socket_timeout=settings.dependency_timeout_seconds,
        )
        try:
            pong = await client.ping()
            info = await client.info(section="server")
        finally:
            await client.aclose()
        if not pong:
            raise RuntimeError("Redis ping returned false")
        return {"version": info.get("redis_version", "unknown")}

    async def check_qdrant() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=settings.dependency_timeout_seconds) as client:
            response = await client.get(
                f"{settings.qdrant_url}/collections",
                headers={"api-key": settings.qdrant_api_key},
            )
            response.raise_for_status()
        return {"endpoint": settings.qdrant_url}

    async def check_minio() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=settings.dependency_timeout_seconds) as client:
            response = await client.get(f"{settings.minio_url}/minio/health/live")
            response.raise_for_status()
        return {"endpoint": settings.minio_url}

    async def check_ollama() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=settings.dependency_timeout_seconds) as client:
            response = await client.get(f"{settings.ollama_base_url}/api/tags")
            response.raise_for_status()
            payload = response.json()

        installed = {model["name"] for model in payload.get("models", [])}
        missing = [model for model in settings.required_ollama_models if model not in installed]
        if missing:
            raise RuntimeError(f"required models not installed: {', '.join(missing)}")
        return {"models": sorted(settings.required_ollama_models)}

    return [
        DependencyCheck("postgres", check_postgres),
        DependencyCheck("redis", check_redis),
        DependencyCheck("qdrant", check_qdrant),
        DependencyCheck("minio", check_minio),
        DependencyCheck("ollama", check_ollama),
    ]


async def dependency_health(settings: Settings) -> dict[str, Any]:
    checks = build_dependency_checks(settings)
    results = await asyncio.gather(
        *[_timed_check(check, settings.dependency_timeout_seconds) for check in checks]
    )
    dependencies = dict(zip((check.name for check in checks), results, strict=True))
    status = "healthy" if all(result["status"] == "healthy" for result in results) else "degraded"
    return {"status": status, "dependencies": dependencies}
