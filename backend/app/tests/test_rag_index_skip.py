"""The RAG indexing task skips unreadable PDFs gracefully (ADR-0013).

A truncated / corrupt source PDF raises ExtractionError deep in
reindex_document. The Celery task must treat that as a non-retryable SKIP
(return "skipped_unreadable") rather than letting it bubble into the
autoretry-for-Exception path and log an ERROR on every corpus backfill.

The engine/session seams are mocked so this needs no database — we only
care that ExtractionError → "skipped_unreadable" and nothing re-raises.
"""

import uuid

import pytest

from app.config import Settings
from app.rag.extraction import ExtractionError
from app.workers import tasks as workers_tasks


class _FakeEngine:
    async def dispose(self) -> None:
        return None


class _FakeSession:
    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def commit(self) -> None:  # pragma: no cover - not reached on the skip path
        return None


async def test_index_skips_unreadable_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        rag_enabled=True,
        rag_database_url="postgresql+asyncpg://rag:rag@localhost:5433/rag",
    )
    monkeypatch.setattr(workers_tasks, "get_settings", lambda: settings)
    monkeypatch.setattr(workers_tasks, "create_async_engine", lambda *a, **k: _FakeEngine())
    monkeypatch.setattr(workers_tasks, "async_sessionmaker", lambda *a, **k: lambda: _FakeSession())

    async def _noop_provision(engine: object) -> None:
        return None

    monkeypatch.setattr("app.rag.db.provision_rag_store", _noop_provision)
    monkeypatch.setattr("app.integrations.llm.get_llm_provider", lambda: object())

    async def _raise_extraction(*a: object, **k: object) -> None:
        raise ExtractionError("could not read PDF: Stream has ended unexpectedly")

    monkeypatch.setattr("app.rag.service.reindex_document", _raise_extraction)

    result = await workers_tasks._index_rag_document_async(str(uuid.uuid4()))
    assert result == "skipped_unreadable"
