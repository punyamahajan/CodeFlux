from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from codeflux.db.models import Base
from codeflux.db.session import normalize_database_url
from codeflux.settings import Settings
from codeflux.storage import Base as LegacyBase


def get_test_database_url() -> str:
    settings = Settings()
    return normalize_database_url(settings.database_url)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    url = get_test_database_url()
    test_engine = create_async_engine(url, poolclass=NullPool)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(LegacyBase.metadata.create_all)
    yield test_engine
    await test_engine.dispose()


@pytest.fixture
async def db_connection(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """Provide a connection wrapped in a transaction that rolls back after each test."""
    async with engine.connect() as connection:
        trans = await connection.begin()
        yield connection
        await trans.rollback()


@pytest.fixture
async def db_session(db_connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """Provide an isolated AsyncSession bound to the rollback transaction."""
    session = AsyncSession(
        bind=db_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        await session.close()


@pytest.fixture
def session_factory(db_connection: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """Provide a session factory bound to the rollback connection for components needing a factory."""
    return async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
