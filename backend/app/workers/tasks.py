import asyncio

from celery.utils.log import get_task_logger
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.integrations.email.client import EmailClient
from app.integrations.impower.client import ImpowerClient
from app.integrations.impower.sync import (
    sync_contacts,
    sync_contracts,
    sync_documents,
    sync_properties,
    sync_units,
)
from app.models import CircularResolution, ResolutionStatus
from app.services.circular import (
    finalize_resolution,
    find_expired_open_resolutions,
    open_due_resolutions,
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


async def _process_due_resolutions_async() -> dict[str, int]:
    """Open due-to-open resolutions and finalize expired ones.

    One commit per finalized resolution so a single failure (e.g. PDF write
    perms) doesn't roll back successful neighbors. Returns counts for log.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    email_client = EmailClient(settings)
    opened = 0
    closed = 0
    failed = 0
    try:
        # Phase A: flip ENTWURF → OFFEN for any resolution whose opens_at has
        # passed. Single commit — these are cheap row updates with no side
        # effects (the invitation email already went out at create time).
        async with session_factory() as session:
            opened = await open_due_resolutions(session)
            if opened:
                await session.commit()
                logger.info("opened %d resolutions (ENTWURF → OFFEN)", opened)

        # Phase B: finalize expired ones. Per-resolution session so failures
        # don't cascade.
        async with session_factory() as scan_session:
            expired = await find_expired_open_resolutions(scan_session)

        for resolution_stub in expired:
            try:
                async with session_factory() as session:
                    # Reload inside the session so the row is attached and we
                    # see latest votes / status. Skip if someone else closed
                    # it between scan and now.
                    fresh = await session.get(CircularResolution, resolution_stub.id)
                    if fresh is None:
                        continue
                    if fresh.status != ResolutionStatus.OFFEN:
                        continue
                    await finalize_resolution(
                        session,
                        fresh,
                        email_client,
                        trigger="beat_scheduled",
                        actor_user_id=None,
                    )
                    await session.commit()
                    closed += 1
                    logger.info(
                        "finalized resolution=%s outcome=%s",
                        fresh.id,
                        fresh.status.value,
                    )
            except Exception:
                failed += 1
                logger.exception("finalize failed for resolution=%s", resolution_stub.id)
    finally:
        await email_client.aclose()
        await engine.dispose()
    return {"opened": opened, "closed": closed, "failed": failed}


@celery_app.task(name="app.workers.tasks.process_due_resolutions")
def process_due_resolutions() -> dict[str, int]:
    """Beat-driven: open new resolutions + finalize expired ones (one tick)."""
    return asyncio.run(_process_due_resolutions_async())
