import asyncio
import base64

from celery.utils.log import get_task_logger
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.integrations.email.announcements import render_publish_email
from app.integrations.email.client import EmailClient, EmailError
from app.integrations.impower.client import ImpowerClient
from app.integrations.impower.sync import (
    sync_contacts,
    sync_contracts,
    sync_documents,
    sync_properties,
    sync_units,
)
from app.integrations.storage.announcements import attachment_path
from app.models import (
    Announcement,
    AnnouncementAttachment,
    CircularResolution,
    Document,
    Property,
    ResolutionStatus,
    SendAttemptStatus,
)
from app.services import announcements as announcements_svc
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


def _read_attachments_for_send(
    attachments: list[AnnouncementAttachment],
) -> list[dict[str, str]]:
    """Convert AnnouncementAttachment rows into Resend's attachment format.

    Mirrors `app/api/v1/tickets._attachments_for_resend` — keep the bytes
    only in scope for the send, and skip rows whose on-disk file is
    missing so a half-uploaded attachment doesn't sink the whole
    fan-out.
    """
    out: list[dict[str, str]] = []
    for att in attachments:
        if not att.storage_url or not att.storage_url.startswith("local-disk:"):
            continue
        suffix = att.storage_url[len("local-disk:") :]
        path = attachment_path(att.id, suffix)
        if not path.exists():
            logger.warning(
                "Skipping announcement attachment %s — file missing at %s",
                att.id,
                path,
            )
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            logger.exception("Could not read announcement attachment %s from disk", att.id)
            continue
        out.append(
            {
                "filename": att.filename,
                "content": base64.b64encode(raw).decode("ascii"),
            }
        )
    return out


async def _publish_due_announcements_async() -> dict[str, int]:
    """Find announcements whose editorial buffer has elapsed and fan out.

    Per-row session so one bad row (missing property, all recipients
    deleted, Resend hiccup) doesn't roll back successful neighbors.
    Mirrors the resolution-finalize pattern. Idempotent — once
    `notification_sent_at` is set the row drops out of the publish-due
    partial index and won't be picked up again on the next tick.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    email_client = EmailClient(settings)

    sent = 0
    skipped = 0
    failed = 0

    try:
        # Phase A: scan in its own session — keeps the read short and
        # releases the connection before the per-row work begins.
        async with session_factory() as scan_session:
            due = await announcements_svc.find_due_for_publish(scan_session)

        for stub in due:
            try:
                async with session_factory() as session:
                    fresh = await session.get(Announcement, stub.id)
                    # Race-guard: someone could have soft-deleted or
                    # already published the row between scan and now.
                    if fresh is None:
                        skipped += 1
                        continue
                    if fresh.deleted_at is not None or fresh.notification_sent_at is not None:
                        skipped += 1
                        continue

                    # Active recipients = auto-resolved minus excluded
                    # plus extras. The override columns are applied
                    # here so a Mitteilung whose audience returns []
                    # but has manually-added `extra_emails` still
                    # fans out to those addresses (v1.2 fix for
                    # "staging property has no portal users").
                    recipient_pairs = await announcements_svc.resolve_active_recipients(
                        session, fresh
                    )
                    if not recipient_pairs:
                        # Both auto + extras resolved to nothing. Mark
                        # published so the row drops out of the
                        # publish-due index — admin can read the
                        # WARN in logs + see zero send-attempts as
                        # the signal.
                        logger.warning(
                            "announcement %s has no active recipients "
                            "(auto + extras = 0); marking published anyway",
                            fresh.id,
                        )
                        announcements_svc.mark_published(fresh)
                        await session.commit()
                        sent += 1
                        continue

                    prop = await session.get(Property, fresh.property_id)
                    property_name = prop.name if prop else "—"

                    attachments = await announcements_svc.list_attachments(session, fresh.id)
                    resend_attachments = _read_attachments_for_send(attachments)

                    # Mark published *before* sending so a Resend hiccup
                    # mid-fan-out doesn't double-send next tick. The
                    # tradeoff: if every send fails, the admin sees a
                    # published row with no emails. The audit log
                    # captures the per-recipient outcome below.
                    announcements_svc.mark_published(fresh)
                    # Narrow the type for mypy — mark_published always
                    # sets notification_sent_at, but the column type is
                    # `datetime | None` so static analysis can't tell.
                    assert fresh.notification_sent_at is not None
                    published_at = fresh.notification_sent_at
                    await session.commit()

                    subject, html, text = render_publish_email(
                        announcement_id=str(fresh.id),
                        title=fresh.title,
                        body=fresh.body,
                        property_name=property_name,
                        published_at=published_at,
                        attachment_count=len(resend_attachments),
                    )

                    # Per-recipient send — no BCC leak, per-address
                    # bounce tracking, and a single bad address can't
                    # take down the rest of the fan-out. Each outcome
                    # is stamped on announcement_send_attempts so the
                    # admin UI can surface failures + offer a manual
                    # retry button.
                    for recipient_user, recipient_email in recipient_pairs:
                        try:
                            await email_client.send(
                                to=[recipient_email],
                                subject=subject,
                                html=html,
                                text=text,
                                attachments=resend_attachments or None,
                            )
                            announcements_svc.record_send_attempt(
                                session,
                                announcement=fresh,
                                recipient_user=recipient_user,
                                recipient_email=recipient_email,
                                status=SendAttemptStatus.SUCCESS,
                            )
                        except EmailError as exc:
                            failed += 1
                            logger.exception(
                                "announcement fan-out failed: announcement=%s recipient=%s code=%s",
                                fresh.id,
                                recipient_email,
                                exc.code,
                            )
                            announcements_svc.record_send_attempt(
                                session,
                                announcement=fresh,
                                recipient_user=recipient_user,
                                recipient_email=recipient_email,
                                status=SendAttemptStatus.FAILED,
                                error_message=str(exc),
                                error_code=exc.code,
                            )

                    # Commit the per-recipient attempt rows in one go.
                    await session.commit()
                    sent += 1
                    logger.info(
                        "published announcement=%s recipients=%d attachments=%d",
                        fresh.id,
                        len(recipient_pairs),
                        len(resend_attachments),
                    )
            except Exception:
                failed += 1
                logger.exception("publish failed for announcement=%s", stub.id)
    finally:
        await email_client.aclose()
        await engine.dispose()

    return {"sent": sent, "skipped": skipped, "failed": failed}


@celery_app.task(name="app.workers.tasks.publish_due_announcements")
def publish_due_announcements() -> dict[str, int]:
    """Beat-driven: fan out any announcements whose 10-min buffer has elapsed."""
    return asyncio.run(_publish_due_announcements_async())


async def _extract_etv_metadata_async(assembly_id_str: str) -> str:
    """Look up one ETV assembly + one of its source invitation PDFs +
    feed them to the LLM extraction service.

    Returns one of:
      - "applied"       — extraction landed on the row
      - "skipped_*"     — see etv_extraction.extract_and_apply
      - "no_source_pdf" — no invitation document with bytes available
      - "assembly_gone" — row deleted between enqueue + run

    The Celery wrapper turns most outcomes into a successful return
    (recorded in audit log). Only real failures (DB error,
    misconfigured provider after env reload) raise + retry.
    """
    import uuid as _uuid

    from sqlalchemy import select

    from app.models import (
        Document,
        EtvAssembly,
    )
    from app.services.etv_extraction import extract_and_apply

    assembly_id = _uuid.UUID(assembly_id_str)
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            assembly = await session.get(EtvAssembly, assembly_id)
            if assembly is None or assembly.deleted_at is not None:
                return "assembly_gone"

            # Find one OWNERS_MEETING_INVITATION document for this
            # property whose issued_date matches (or is within 1 day
            # of) the assembly's scheduled_start. Multiple PDFs per
            # meeting (one per Eigentümer) — any of them works.
            day = assembly.scheduled_start.date()
            doc = await session.scalar(
                select(Document).where(
                    Document.property_id == assembly.property_id,
                    Document.impower_source_type == "OWNERS_MEETING_INVITATION",
                    Document.deleted_at.is_(None),
                    Document.issued_date == day,
                ).limit(1)
            )
            if doc is None:
                logger.info(
                    "extract_etv_metadata: no invitation document for "
                    "assembly=%s property=%s day=%s",
                    assembly_id, assembly.property_id, day,
                )
                return "no_source_pdf"

            # Try local storage first; fall back to a one-shot Impower
            # download. Both paths can return None for "no bytes
            # available", in which case we record + give up.
            pdf_bytes = await _fetch_invitation_pdf_bytes(doc)
            if pdf_bytes is None:
                logger.info(
                    "extract_etv_metadata: no PDF bytes available for "
                    "document=%s (impower_id=%s)",
                    doc.id, doc.impower_id,
                )
                return "no_source_pdf"

            outcome = await extract_and_apply(
                session,
                assembly_id=assembly_id,
                pdf_bytes=pdf_bytes,
                source_document_id=doc.id,
            )
            await session.commit()
            return outcome
    finally:
        await engine.dispose()


async def _fetch_invitation_pdf_bytes(doc: Document) -> bytes | None:
    """Best-effort source the PDF bytes for an invitation document.

    Order:
      1. Local storage_url (set by §1.4d iter 2 once it lands — until
         then, NULL for Impower-sourced docs).
      2. Impower /documents/{id}/download endpoint.

    Returns None if neither source produces bytes; the Celery task
    short-circuits and records "no_source_pdf" in the audit log.
    """
    from pathlib import Path

    from app.integrations.impower.client import ImpowerClient

    if doc.storage_url:
        p = Path(doc.storage_url)
        if p.exists():  # noqa: ASYNC240 — Celery task already runs blocking IO
            try:
                return p.read_bytes()  # noqa: ASYNC240
            except OSError:
                logger.exception("failed to read local invitation %s", p)

    if doc.impower_id is None:
        return None
    settings = get_settings()
    if not settings.impower_api_token:
        return None
    async with ImpowerClient(
        settings.impower_api_base, settings.impower_api_token
    ) as client:
        return await client.download_document_content(int(doc.impower_id))


@celery_app.task(
    name="app.workers.tasks.extract_etv_metadata",
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=300,
)
def extract_etv_metadata(assembly_id: str) -> str:
    """Async LLM extraction for one assembly. Enqueued by the backfill
    helper + (later) the Impower document-sync upsert path."""
    return asyncio.run(_extract_etv_metadata_async(assembly_id))
