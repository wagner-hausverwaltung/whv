"""Tests for enqueue_document_indexing (ADR-0013 #148): the post-sync /
backfill enqueue helper — gating, only_new, source filter, and limit. The
Celery .delay is monkeypatched so nothing is actually queued. Scoped to a
single property so the shared test DB can't bleed in other docs.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.models.document import Document, DocumentKind
from app.rag.models import RagDocument
from app.rag.service import enqueue_document_indexing
from app.tests._factories import make_org, make_property
from app.workers import tasks as workers_tasks

_RAG_DSN = "postgresql+asyncpg://rag:rag@localhost:5433/rag"


def _rag_on() -> Settings:
    return Settings(rag_enabled=True, rag_database_url=_RAG_DSN)


async def test_enqueue_document_indexing(
    test_engine: AsyncEngine,
    session: AsyncSession,
    rag_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sessionmaker = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sessionmaker() as setup:
        doc_a = Document(
            organization_id=org.id, property_id=prop.id, name="A",
            kind=DocumentKind.RECHNUNG, impower_id=910001,
        )
        doc_b = Document(
            organization_id=org.id, property_id=prop.id, name="B",
            kind=DocumentKind.RECHNUNG, impower_id=910002,
        )
        doc_no_source = Document(
            organization_id=org.id, property_id=prop.id, name="C", kind=DocumentKind.RECHNUNG,
        )
        setup.add_all([doc_a, doc_b, doc_no_source])
        await setup.commit()
        for doc in (doc_a, doc_b, doc_no_source):
            await setup.refresh(doc)

    # doc_a is already indexed in the RAG store.
    rag_session.add(
        RagDocument(
            document_id=doc_a.id,
            organization_id=org.id,
            extracted_text="x",
            content_hash="hash",
            ocr_engine="pdf-text-layer",
            visibility="ALL",
        )
    )
    await rag_session.flush()

    enqueued: list[str] = []

    def _record(doc_id: str) -> None:
        enqueued.append(doc_id)

    monkeypatch.setattr(workers_tasks.index_rag_document, "delay", _record)

    # Gated off → no-op.
    assert (
        await enqueue_document_indexing(
            session, rag_session, settings=get_settings(), property_id=prop.id
        )
        == 0
    )
    assert enqueued == []

    # only_new → only doc_b (doc_a indexed, doc_no_source has no fetchable source).
    count_new = await enqueue_document_indexing(
        session, rag_session, settings=_rag_on(), only_new=True, property_id=prop.id
    )
    assert count_new == 1
    assert enqueued == [str(doc_b.id)]

    # all → doc_a + doc_b (no_source still excluded).
    enqueued.clear()
    count_all = await enqueue_document_indexing(
        session, rag_session, settings=_rag_on(), only_new=False, property_id=prop.id
    )
    assert count_all == 2
    assert set(enqueued) == {str(doc_a.id), str(doc_b.id)}

    # limit caps the enqueue.
    enqueued.clear()
    count_limited = await enqueue_document_indexing(
        session, rag_session, settings=_rag_on(), only_new=False, property_id=prop.id, limit=1
    )
    assert count_limited == 1
    assert len(enqueued) == 1
