import asyncio
import base64
import uuid
from pathlib import Path

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
    NotificationCategory,
    NotificationChannel,
    Property,
    ResolutionStatus,
    SendAttemptStatus,
)
from app.services import announcements as announcements_svc
from app.services import notification_prefs, push
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


async def _backfill_etv_and_notify_async() -> dict[str, int]:
    """Post-sync ETV step: turn freshly-imported OWNERS_MEETING_INVITATION
    documents into EtvAssembly stubs, then nudge each property's owners +
    Beirat (email + push) that a new Einladung is available.

    Kept separate from `_sync_all_async` so the document sync stays a
    pure mirror and this side-effecting step is independently testable.
    Best-effort throughout: a notification hiccup logs but never fails
    the nightly sync. The backfill is idempotent and the notify step
    only fires for genuinely-recent invitations, so re-running nightly
    doesn't re-spam owners.
    """
    from sqlalchemy import select

    from app.models import Organization
    from app.services.etv import (
        backfill_assemblies_from_invitations,
        notify_owners_of_new_invitations,
    )

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    email_client = EmailClient(settings)
    created_ids: list[uuid.UUID] = []
    notified = 0
    try:
        async with session_factory() as session:
            orgs = (await session.execute(select(Organization))).scalars().all()
            for org in orgs:
                _, _, ids = await backfill_assemblies_from_invitations(
                    session, organization_id=org.id
                )
                created_ids.extend(ids)
            await session.commit()
            notified = await notify_owners_of_new_invitations(
                session,
                assembly_ids=created_ids,
                email_client=email_client,
            )
    finally:
        await engine.dispose()

    # Auto-extract: enqueue an LLM extraction for each freshly-created
    # stub so its agenda + metadata (Termin, Ort, Teams-URL, …) fill in
    # automatically. The extraction task already falls back to the
    # property+date OWNERS_MEETING_INVITATION document for the PDF bytes
    # when no PDF was uploaded — so the full Impower-push → auto-create
    # → auto-extract → notify chain needs nothing manual. Mirrors the
    # CLI `--extract` flag. Enqueued after the engine is disposed (rows
    # are committed) so workers find them. No-op if Gemini is
    # unconfigured (the task logs + skips).
    if created_ids:
        for aid in created_ids:
            extract_etv_metadata.delay(str(aid))

    logger.info(
        "etv backfill: created=%d owners_notified=%d extraction_enqueued=%d",
        len(created_ids),
        notified,
        len(created_ids),
    )
    return {
        "etv_assemblies_created": len(created_ids),
        "etv_owners_notified": notified,
    }


async def _notify_new_documents_async() -> dict[str, int]:
    """Post-sync pass: email + push owners about freshly-synced
    relevant documents (Jahresabrechnung / Wirtschaftsplan / Protokoll /
    Umlaufbeschluss), scoped to whoever may see each doc. Idempotent via
    `documents.notified_at`. Best-effort — own session + engine."""
    from app.services.document_notify import notify_new_documents

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    email_client = EmailClient(settings)
    notified = 0
    try:
        async with session_factory() as session:
            notified = await notify_new_documents(session, email_client=email_client)
    finally:
        await engine.dispose()
    logger.info("document notify: docs_notified=%d", notified)
    return {"documents_notified": notified}


async def _notify_plan_adjustments_async() -> dict[str, int]:
    """Post-sync pass: poll each active owner contract for INFORMED
    plan-adjustment suggestions and notify the owner(s) that their
    Hausgeld is changing. Own engine + Redis client (the module Redis is
    request-scoped and not initialised in the worker)."""
    from redis.asyncio import from_url

    from app.integrations.impower.client import ImpowerClient
    from app.services.plan_adjustment_notify import notify_plan_adjustments

    settings = get_settings()
    if not settings.impower_api_token:
        return {"plan_adjustments_notified": 0}

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    email_client = EmailClient(settings)
    redis = from_url(settings.redis_url, decode_responses=True)  # type: ignore[no-untyped-call]
    notified = 0
    try:
        async with (
            ImpowerClient(settings.impower_api_base, settings.impower_api_token) as client,
            session_factory() as session,
        ):
            notified = await notify_plan_adjustments(
                session, client=client, redis=redis, email_client=email_client
            )
    finally:
        await redis.aclose()
        await engine.dispose()
    logger.info("plan-adjustment notify: notified=%d", notified)
    return {"plan_adjustments_notified": notified}


async def _enqueue_rag_indexing_async() -> dict[str, int]:
    """Post-sync: enqueue RAG indexing for newly-synced documents AND refresh
    every master-data card (ADR-0013).

    No-op when rag_enabled is off, so it stays dormant until the assistant is
    switched on. Documents use the only_new gate — only docs not yet in the RAG
    store are enqueued; the content-hash skip in index_rag_document is the
    second line of defence so a re-enqueue of an unchanged doc costs no
    embedding call. Master-data cards (Dienstleister + owner/tenant contacts)
    are re-enqueued in full every night — they're cheap and the content-hash
    skip means only cards whose underlying data changed (new invoices → vendor
    totals, new/changed contracts → contact info) actually re-embed. That keeps
    the cards fresh as contracts/invoices churn in Impower.
    """
    settings = get_settings()
    if not settings.rag_enabled:
        return {}

    from app.rag.db import provision_rag_store
    from app.rag.service import enqueue_document_indexing, enqueue_masterdata_indexing

    app_engine = create_async_engine(settings.database_url)
    rag_engine = create_async_engine(settings.rag_database_url)
    try:
        await provision_rag_store(rag_engine)
        app_factory = async_sessionmaker(app_engine, expire_on_commit=False)
        rag_factory = async_sessionmaker(rag_engine, expire_on_commit=False)
        async with app_factory() as app_session, rag_factory() as rag_session:
            enqueued = await enqueue_document_indexing(
                app_session, rag_session, settings=settings, only_new=True
            )
            cards = await enqueue_masterdata_indexing(app_session, settings=settings)
    finally:
        await app_engine.dispose()
        await rag_engine.dispose()
    logger.info("rag indexing: enqueued=%d new documents, %d master-data cards", enqueued, cards)
    return {"rag_indexing_enqueued": enqueued, "rag_masterdata_enqueued": cards}


@celery_app.task(name="app.workers.tasks.sync_all_impower")
def sync_all_impower() -> dict[str, int]:
    """Celery task wrapper. Bridges Celery's sync model to our async sync layer.

    Runs the full entity sync first, then two isolated post-sync
    phases — the ETV invitation backfill + owner notification, and the
    new-document notification — each in its own session so a problem in
    one can't roll back the mirror sync or the other.
    """
    counts = asyncio.run(_sync_all_async())
    try:
        counts.update(asyncio.run(_backfill_etv_and_notify_async()))
    except Exception:
        logger.exception("etv backfill/notify phase failed")
    try:
        counts.update(asyncio.run(_notify_new_documents_async()))
    except Exception:
        logger.exception("document notify phase failed")
    try:
        counts.update(asyncio.run(_notify_plan_adjustments_async()))
    except Exception:
        logger.exception("plan-adjustment notify phase failed")
    try:
        counts.update(asyncio.run(_enqueue_rag_indexing_async()))
    except Exception:
        logger.exception("rag indexing enqueue phase failed")
    return counts


async def _reconcile_impower_async() -> dict[str, dict[str, int]]:
    """Compare local mirror row-counts vs. Impower live counts and
    emit a Sentry warning if the diff exceeds the thresholds in
    `services/reconciliation.py`. Read-only — never writes."""
    from app.services.reconciliation import alert_on_drift, reconcile

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    summary: dict[str, dict[str, int]] = {}
    try:
        async with (
            ImpowerClient(settings.impower_api_base, settings.impower_api_token) as client,
            session_factory() as session,
        ):
            diffs = await reconcile(session, client)
            alert_on_drift(diffs)
            for d in diffs:
                summary[d.entity] = {
                    "mirror": d.mirror_count,
                    "impower": d.impower_count,
                    "diff": d.diff,
                }
                logger.info(
                    "reconcile %s: mirror=%d impower=%d diff=%d drifted=%s",
                    d.entity,
                    d.mirror_count,
                    d.impower_count,
                    d.diff,
                    d.is_drifted,
                )
    finally:
        await engine.dispose()
    return summary


@celery_app.task(name="app.workers.tasks.reconcile_impower")
def reconcile_impower() -> dict[str, dict[str, int]]:
    """Daily watchdog — Sentry alert on drift between mirror + Impower."""
    return asyncio.run(_reconcile_impower_async())


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

                    # Notification-preference split (category
                    # ANNOUNCEMENT). recipient_user is None for
                    # manually-added external extra_emails — those have
                    # no account, so no preference: they always get the
                    # email and never a push.
                    pair_user_ids = [ru.id for ru, _ in recipient_pairs if ru is not None]
                    email_ok_ids = set(
                        await notification_prefs.filter_user_ids(
                            session,
                            user_ids=pair_user_ids,
                            category=NotificationCategory.ANNOUNCEMENT,
                            channel=NotificationChannel.EMAIL,
                        )
                    )
                    push_ids = await notification_prefs.filter_user_ids(
                        session,
                        user_ids=pair_user_ids,
                        category=NotificationCategory.ANNOUNCEMENT,
                        channel=NotificationChannel.PUSH,
                    )

                    # Per-recipient send — no BCC leak, per-address
                    # bounce tracking, and a single bad address can't
                    # take down the rest of the fan-out. Each outcome
                    # is stamped on announcement_send_attempts so the
                    # admin UI can surface failures + offer a manual
                    # retry button.
                    for recipient_user, recipient_email in recipient_pairs:
                        # Skip registered users who turned off the
                        # Mitteilungen email channel (they may still get
                        # the push below). External addresses (no user)
                        # always proceed.
                        if recipient_user is not None and recipient_user.id not in email_ok_ids:
                            continue
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

                    # Push fan-out to the preference-filtered user set —
                    # net-new for Mitteilungen (previously email-only).
                    # No-op when APNs is unconfigured. Deep-links to the
                    # announcement so a tap opens it in the News tab.
                    await push.notify_users(
                        session,
                        user_ids=push_ids,
                        title="Neue Mitteilung",
                        body=f"{property_name}: {fresh.title}",
                        deep_link=f"whv://announcement/{fresh.id}",
                        thread_id=f"announcement-{fresh.id}",
                    )

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
    from sqlalchemy import select

    from app.models import (
        Document,
        EtvAssembly,
    )
    from app.services.etv_extraction import extract_and_apply

    assembly_id = uuid.UUID(assembly_id_str)
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            assembly = await session.get(EtvAssembly, assembly_id)
            if assembly is None or assembly.deleted_at is not None:
                return "assembly_gone"

            # Source order for PDF bytes:
            #   1. Admin-uploaded invitation PDF on the assembly row
            #      (the canonical path now that Verwalter drives ETV
            #      data entry — pivoted away from Impower-pulling).
            #   2. Impower OWNERS_MEETING_INVITATION document for
            #      this property+date — kept as a fallback so future
            #      production Impower instances that DO serve PDFs
            #      "just work" without re-wiring.
            pdf_bytes: bytes | None = None
            source_doc_id: uuid.UUID | None = None

            if assembly.invitation_pdf_url:
                inv_path = Path(assembly.invitation_pdf_url)
                if not inv_path.is_absolute():
                    inv_path = Path(settings.etv_invitation_dir) / inv_path.name
                if inv_path.exists():
                    try:
                        pdf_bytes = inv_path.read_bytes()
                    except OSError:
                        logger.exception("failed to read uploaded invitation %s", inv_path)

            if pdf_bytes is None:
                day = assembly.scheduled_start.date()
                doc = await session.scalar(
                    select(Document)
                    .where(
                        Document.property_id == assembly.property_id,
                        Document.impower_source_type == "OWNERS_MEETING_INVITATION",
                        Document.deleted_at.is_(None),
                        Document.issued_date == day,
                    )
                    .limit(1)
                )
                if doc is not None:
                    pdf_bytes = await _fetch_invitation_pdf_bytes(doc)
                    if pdf_bytes is not None:
                        source_doc_id = doc.id
                else:
                    logger.info(
                        "extract_etv_metadata: no invitation source "
                        "(neither uploaded nor Impower) for assembly=%s",
                        assembly_id,
                    )

            if pdf_bytes is None:
                return "no_source_pdf"

            outcome = await extract_and_apply(
                session,
                assembly_id=assembly_id,
                pdf_bytes=pdf_bytes,
                source_document_id=source_doc_id,
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
    async with ImpowerClient(settings.impower_api_base, settings.impower_api_token) as client:
        return await client.download_document_content(int(doc.impower_id))


async def _read_local_invitation(p: Path) -> bytes | None:
    """Read an admin-uploaded invitation PDF from local disk. Celery's
    already-blocking model makes the sync IO acceptable here."""
    try:
        return p.read_bytes()  # noqa: ASYNC240
    except OSError:
        logger.exception("failed to read uploaded invitation %s", p)
        return None


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


async def _extract_etv_protocol_async(assembly_id_str: str) -> str:
    """Read the signed Protokoll PDF + merge Beschluss outcomes +
    Diskussion into the existing agenda.

    Outcomes:
      - "applied"       — extraction landed
      - "skipped_*"     — see etv_protocol_extraction.extract_protocol_and_apply
      - "no_source_pdf" — protocol_pdf_url is null or the file is missing
      - "assembly_gone" — row deleted between enqueue + run
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models import EtvAssembly
    from app.services.etv_protocol_extraction import extract_protocol_and_apply

    assembly_id = uuid.UUID(assembly_id_str)
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            assembly = await session.get(EtvAssembly, assembly_id)
            if assembly is None or assembly.deleted_at is not None:
                return "assembly_gone"
            if not assembly.protocol_pdf_url:
                logger.info(
                    "extract_etv_protocol: no protocol uploaded for assembly=%s",
                    assembly_id,
                )
                return "no_source_pdf"

            p = Path(assembly.protocol_pdf_url)
            if not p.is_absolute():
                p = Path(settings.etv_protocol_dir) / p.name
            if not p.exists():
                logger.info("extract_etv_protocol: protocol file missing at %s", p)
                return "no_source_pdf"
            try:
                pdf_bytes = p.read_bytes()
            except OSError:
                logger.exception("failed to read protocol %s", p)
                return "no_source_pdf"

            outcome = await extract_protocol_and_apply(
                session,
                assembly_id=assembly_id,
                pdf_bytes=pdf_bytes,
                source_document_id=None,
            )
            await session.commit()
            return outcome
    finally:
        await engine.dispose()


@celery_app.task(
    name="app.workers.tasks.extract_etv_protocol",
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=300,
)
def extract_etv_protocol(assembly_id: str) -> str:
    """Async LLM extraction of the signed Protokoll. Enqueued by the
    /admin/assemblies/{id}/protocol upload endpoint immediately after
    the bytes hit disk."""
    return asyncio.run(_extract_etv_protocol_async(assembly_id))


async def _index_rag_document_async(document_id_str: str) -> str:
    """Index one Document into the pgvector RAG store (ADR-0013).

    No-op ("rag_disabled") unless rag_enabled, so this ships dark in prod.
    Provisions the store on its own engine (the worker doesn't run the app
    lifespan), then resolves + embeds + persists the document. Returns
    "indexed:<n>", "skipped" (unchanged hash), "no_source" (no bytes), or
    "rag_disabled"."""
    settings = get_settings()
    if not settings.rag_enabled:
        return "rag_disabled"

    from app.integrations.llm import get_llm_provider
    from app.rag.db import provision_rag_store
    from app.rag.extraction import ExtractionError
    from app.rag.service import reindex_document

    document_id = uuid.UUID(document_id_str)
    app_engine = create_async_engine(settings.database_url)
    rag_engine = create_async_engine(settings.rag_database_url)
    try:
        await provision_rag_store(rag_engine)
        app_factory = async_sessionmaker(app_engine, expire_on_commit=False)
        rag_factory = async_sessionmaker(rag_engine, expire_on_commit=False)
        async with app_factory() as app_session, rag_factory() as rag_session:
            try:
                result = await reindex_document(
                    app_session,
                    rag_session,
                    get_llm_provider(),
                    document_id=document_id,
                    settings=settings,
                )
            except ExtractionError as exc:
                # Unrecoverable: the source bytes aren't a readable PDF
                # (truncated / corrupt). Retrying can't un-corrupt them, so
                # skip this document gracefully instead of burning the retry
                # budget and logging an ERROR traceback on every corpus
                # backfill. Transient failures (network fetch, Gemini 429/503)
                # are other exception types and still autoretry as before.
                logger.warning(
                    "RAG indexing skipped for document %s — unreadable PDF: %s",
                    document_id,
                    exc,
                )
                return "skipped_unreadable"
            if result is None:
                return "no_source"
            await rag_session.commit()
            return "skipped" if result.skipped else f"indexed:{result.chunk_count}"
    finally:
        await app_engine.dispose()
        await rag_engine.dispose()


@celery_app.task(
    name="app.workers.tasks.index_rag_document",
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=300,
)
def index_rag_document(document_id: str) -> str:
    """Index one Document into the RAG store (ADR-0013). Enqueued by a manual
    backfill or the post-sync hook (later); no-op when rag_enabled is off."""
    return asyncio.run(_index_rag_document_async(document_id))


async def _index_rag_masterdata_async(
    property_id_str: str, entity_id_str: str, card_type: str = "dienstleister"
) -> str:
    """Index one master-data card into the RAG store (ADR-0013 §4).

    ``card_type`` routes to the Dienstleister, contact (owner/tenant), or ETV
    (Eigentümerversammlung) renderer; ``entity_id`` is the vendor contact /
    contact / assembly id accordingly. No-op ("rag_disabled") unless
    rag_enabled. Returns "indexed:<n>", "skipped" (unchanged card), or
    "no_entity" (the entity no longer belongs to that property)."""
    settings = get_settings()
    if not settings.rag_enabled:
        return "rag_disabled"

    from app.integrations.llm import get_llm_provider
    from app.rag.db import provision_rag_store
    from app.rag.service import (
        reindex_contact_card,
        reindex_dienstleister_card,
        reindex_etv_card,
    )

    property_id = uuid.UUID(property_id_str)
    entity_id = uuid.UUID(entity_id_str)
    app_engine = create_async_engine(settings.database_url)
    rag_engine = create_async_engine(settings.rag_database_url)
    try:
        await provision_rag_store(rag_engine)
        app_factory = async_sessionmaker(app_engine, expire_on_commit=False)
        rag_factory = async_sessionmaker(rag_engine, expire_on_commit=False)
        async with app_factory() as app_session, rag_factory() as rag_session:
            provider = get_llm_provider()
            if card_type == "etv":
                result = await reindex_etv_card(
                    app_session,
                    rag_session,
                    provider,
                    property_id=property_id,
                    assembly_id=entity_id,
                )
            elif card_type == "contact":
                result = await reindex_contact_card(
                    app_session,
                    rag_session,
                    provider,
                    property_id=property_id,
                    contact_id=entity_id,
                )
            else:
                result = await reindex_dienstleister_card(
                    app_session,
                    rag_session,
                    provider,
                    property_id=property_id,
                    contact_id=entity_id,
                )
            if result is None:
                return "no_entity"
            await rag_session.commit()
            return "skipped" if result.skipped else f"indexed:{result.chunk_count}"
    finally:
        await app_engine.dispose()
        await rag_engine.dispose()


@celery_app.task(
    name="app.workers.tasks.index_rag_masterdata",
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=300,
)
def index_rag_masterdata(property_id: str, entity_id: str, card_type: str = "dienstleister") -> str:
    """Index one master-data card (ADR-0013 §4): a Dienstleister card
    (``card_type="dienstleister"``), an owner/tenant contact card
    (``card_type="contact"``), or an ETV card (``card_type="etv"``). Enqueued by
    the master-data backfill; no-op when rag_enabled is off."""
    return asyncio.run(_index_rag_masterdata_async(property_id, entity_id, card_type))
