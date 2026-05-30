"""One-time RAG backfill: enqueue document indexing for the existing corpus
(ADR-0013).

Enqueues ``index_rag_document`` Celery tasks — run it with a worker up. The
default only enqueues documents not yet in the RAG store; ``--all`` re-indexes
everything (the content-hash skip makes that idempotent). No-op when
``rag_enabled`` is off.

Usage:
    python -m app.scripts.backfill_rag [--all] [--property <uuid>] [--limit N]
"""

import argparse
import asyncio
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.rag.db import provision_rag_store
from app.rag.service import enqueue_document_indexing, enqueue_masterdata_indexing


async def _run(
    *,
    only_new: bool,
    property_id: uuid.UUID | None,
    limit: int | None,
    masterdata: bool,
) -> int:
    settings = get_settings()
    if not settings.rag_enabled:
        print("rag_enabled is off — nothing to do.")
        return 0
    app_engine = create_async_engine(settings.database_url)
    rag_engine = create_async_engine(settings.rag_database_url)
    try:
        await provision_rag_store(rag_engine)
        app_factory = async_sessionmaker(app_engine, expire_on_commit=False)
        rag_factory = async_sessionmaker(rag_engine, expire_on_commit=False)
        async with app_factory() as app_session, rag_factory() as rag_session:
            if masterdata:
                # Master-data enqueue only reads the app DB (vendors) — the
                # rag_session isn't needed, but we keep the store provisioned.
                return await enqueue_masterdata_indexing(
                    app_session,
                    settings=settings,
                    property_id=property_id,
                    limit=limit,
                )
            return await enqueue_document_indexing(
                app_session,
                rag_session,
                settings=settings,
                only_new=only_new,
                property_id=property_id,
                limit=limit,
            )
    finally:
        await app_engine.dispose()
        await rag_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Enqueue RAG indexing.")
    parser.add_argument("--all", action="store_true", help="re-index all docs, not just new ones")
    parser.add_argument(
        "--masterdata",
        action="store_true",
        help="index Dienstleister master-data cards instead of documents (ADR-0013 §4)",
    )
    parser.add_argument("--property", type=str, default=None, help="one property id (UUID)")
    parser.add_argument("--limit", type=int, default=None, help="cap how many items to enqueue")
    args = parser.parse_args()

    property_id = uuid.UUID(args.property) if args.property else None
    count = asyncio.run(
        _run(
            only_new=not args.all,
            property_id=property_id,
            limit=args.limit,
            masterdata=args.masterdata,
        )
    )
    unit = "Dienstleister card" if args.masterdata else "document"
    print(f"enqueued {count} {unit}(s) for RAG indexing.")


if __name__ == "__main__":
    main()
