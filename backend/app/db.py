from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str) -> None:
    global _engine, _sessionmaker
    _engine = create_async_engine(database_url, pool_pre_ping=True, future=True)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)


async def close_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def get_session() -> AsyncIterator[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("Database not initialized — call init_engine first")
    async with _sessionmaker() as session:
        yield session


async def ping_db() -> bool:
    if _engine is None:
        return False
    try:
        async with _engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        return False
    return True
