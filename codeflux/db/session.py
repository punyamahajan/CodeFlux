from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from codeflux.settings import Settings


def normalize_database_url(url: str) -> str:
    """Normalize database URLs for asyncpg and Neon Postgres."""
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    if "sslmode=require" in url:
        url = url.replace("sslmode=require", "ssl=require")
    return url


def create_engine(database_url: str | None = None, **kwargs: Any) -> AsyncEngine:
    settings = Settings()
    url = normalize_database_url(database_url or settings.database_url)
    kwargs.setdefault("pool_pre_ping", True)
    return create_async_engine(url, **kwargs)


def create_session_maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


class Database:
    """Async database manager for OmniKey."""

    def __init__(self, url: str | None = None, **kwargs: Any):
        settings = Settings()
        raw_url = url or settings.database_url
        self.url = normalize_database_url(raw_url)
        kwargs.setdefault("pool_pre_ping", True)
        self.engine: AsyncEngine = create_async_engine(self.url, **kwargs)
        self.sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        await self.engine.dispose()


async def get_db_session() -> AsyncIterator[AsyncSession]:
    settings = Settings()
    engine = create_engine(settings.database_url)
    session_maker = create_session_maker(engine)
    try:
        async with session_maker() as session:
            yield session
    finally:
        await engine.dispose()
