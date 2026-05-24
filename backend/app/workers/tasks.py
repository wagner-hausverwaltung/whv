import asyncio

from celery.utils.log import get_task_logger
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.integrations.impower.client import ImpowerClient
from app.integrations.impower.sync import (
    sync_contacts,
    sync_contracts,
    sync_documents,
    sync_properties,
    sync_units,
)
from app.workers.celery_app import celery_app

logger = get_task_logger(__name__)


async def _sync_all_async() -> dict[str, int]:
    """Run a full Impower sync (properties → units → contacts → contracts → documents).

    Each step uses the same async session + client; failures bubble up so
    Celery records the task as failed and the next nightly run retries.
    Returns per-entity upserted counts for visibility.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    counts: dict[str, int] = {}
    try:
        async with (
            ImpowerClient(settings.impower_api_base, settings.impower_api_token) as client,
            session_factory() as session,
        ):
            for name, fn in (
                ("properties", sync_properties),
                ("units", sync_units),
                ("contacts", sync_contacts),
                ("contracts", sync_contracts),
                ("documents", sync_documents),
            ):
                stats = await fn(session, client)
                counts[name] = stats.upserted
                logger.info(
                    "sync %s: fetched=%d upserted=%d skipped=%d",
                    name,
                    stats.fetched,
                    stats.upserted,
                    stats.skipped,
                )
    finally:
        await engine.dispose()
    return counts


@celery_app.task(name="app.workers.tasks.sync_all_impower")
def sync_all_impower() -> dict[str, int]:
    """Celery task wrapper. Bridges Celery's sync model to our async sync layer."""
    return asyncio.run(_sync_all_async())
