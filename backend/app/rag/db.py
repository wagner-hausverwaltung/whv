"""Async engine + store bootstrap for the RAG vector DB (ADR-0013).

A SEPARATE Postgres (the `vectordb` pgvector container) from the app DB.
Mirrors the ``app.db`` engine lifecycle but bound to
``settings.rag_database_url``. ``init_rag_store`` provisions the pgvector
extension + tables/indexes; because the store is a derived, rebuildable
cache it's ``create_all`` rather than Alembic (see ``app.rag.models``).

Wired into the app lifespan only when ``settings.rag_enabled`` — until
then nothing here ever opens a connection.
"""

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.rag.models import RagBase

_rag_engine: AsyncEngine | None = None
_rag_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_rag_engine(database_url: str) -> None:
    global _rag_engine, _rag_sessionmaker
    _rag_engine = create_async_engine(database_url, pool_pre_ping=True, future=True)
    _rag_sessionmaker = async_sessionmaker(_rag_engine, expire_on_commit=False)


async def close_rag_engine() -> None:
    global _rag_engine, _rag_sessionmaker
    if _rag_engine is not None:
        await _rag_engine.dispose()
    _rag_engine = None
    _rag_sessionmaker = None


async def get_rag_session() -> AsyncIterator[AsyncSession]:
    if _rag_sessionmaker is None:
        raise RuntimeError("RAG store not initialized — call init_rag_engine first")
    async with _rag_sessionmaker() as session:
        yield session


async def ping_rag_db() -> bool:
    if _rag_engine is None:
        return False
    try:
        async with _rag_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


async def init_rag_store() -> None:
    """Provision the pgvector extension + the RAG tables/indexes.

    Idempotent: ``CREATE EXTENSION IF NOT EXISTS`` + ``create_all``
    (which checks the catalog first). Safe to call on every boot while
    ``rag_enabled``. The extension is created in the same transaction,
    BEFORE ``create_all``, so the ``vector`` column type + HNSW operator
    class exist when the table/index DDL runs.
    """
    if _rag_engine is None:
        raise RuntimeError("RAG store not initialized — call init_rag_engine first")
    async with _rag_engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(RagBase.metadata.create_all)
