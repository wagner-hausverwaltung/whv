import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app import models  # noqa: F401  ensure models register on Base.metadata
from app.config import get_settings
from app.db import Base
from app.rag.models import RagBase

_ENUM_TYPES = (
    "contact_kind",
    "preferred_channel",
    "notification_category",
    "contract_type",
    "document_kind",
    "document_state",
    "document_visibility",
    "property_state",
    "property_type",
    "resolution_mode",
    "resolution_status",
    "send_attempt_status",
    "ticket_category",
    "ticket_message_source",
    "ticket_share_scope",
    "ticket_status",
    "unit_type",
    "user_role",
    "vote_choice",
)


@pytest.fixture(autouse=True)
def _block_outbound_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """Safety net: NO test may hit the real Resend API.

    The per-file ``stub_email`` fixtures only cover the FastAPI dependency
    path, but the Celery tasks construct ``EmailClient(settings)`` inline
    (app/workers/tasks.py). With a real RESEND_API_KEY in a dev .env that
    silently sent live mail to the ``user-*@test.de`` fixture addresses on
    every run. We no-op the send at the source for every test. Tests that
    assert on email use ``_StubEmailClient`` (a separate class), so this does
    not interfere with them.
    """

    async def _noop_send(self: object, **_kwargs: object) -> str:
        return "test-noop-message-id"

    monkeypatch.setattr("app.integrations.email.client.EmailClient.send", _noop_send)


@pytest_asyncio.fixture(scope="session")
async def test_engine() -> AsyncIterator[AsyncEngine]:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        for type_name in _ENUM_TYPES:
            await conn.execute(text(f"DROP TYPE IF EXISTS {type_name} CASCADE"))
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        for type_name in _ENUM_TYPES:
            await conn.execute(text(f"DROP TYPE IF EXISTS {type_name} CASCADE"))
    await engine.dispose()


@pytest_asyncio.fixture
async def session(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with test_engine.connect() as conn:
        trans = await conn.begin()
        sessionmaker = async_sessionmaker(bind=conn, expire_on_commit=False)
        async with sessionmaker() as session:
            yield session
            await session.close()
        await trans.rollback()


@pytest_asyncio.fixture(scope="session")
async def rag_test_engine() -> AsyncIterator[AsyncEngine]:
    """Session-scoped engine for the pgvector RAG store (ADR-0013). Skips
    the whole RAG-store test surface when RAG_DATABASE_URL is unset or
    unreachable (a dev without the vectordb container) — CI sets it via the
    pgvector service in backend.yml."""
    url = os.environ.get("RAG_DATABASE_URL")
    if not url:
        pytest.skip("RAG_DATABASE_URL not set — RAG store tests skipped")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        await engine.dispose()
        pytest.skip("RAG store not reachable")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(RagBase.metadata.drop_all)
        await conn.run_sync(RagBase.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(RagBase.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def rag_session(rag_test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with rag_test_engine.connect() as conn:
        trans = await conn.begin()
        sessionmaker = async_sessionmaker(bind=conn, expire_on_commit=False)
        async with sessionmaker() as session:
            yield session
            await session.close()
        await trans.rollback()
