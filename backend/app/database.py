from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

settings = get_settings()


def async_postgres_dsn() -> str:
    return settings.postgres_dsn.replace("postgresql://", "postgresql+psycopg://", 1)


engine: AsyncEngine = create_async_engine(
    async_postgres_dsn(),
    pool_pre_ping=True,
)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
