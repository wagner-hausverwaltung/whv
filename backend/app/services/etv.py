"""Eigentümerversammlung service helpers.

The hot paths are: load an assembly with its full agenda + discussion in
one round-trip (detail view), and create / update / re-order agenda
items in a single transaction (admin builder UI).

We deliberately keep these as plain async helpers — no session lifecycle
inside, the caller commits — so the same primitives serve both the
admin REST handlers and any future Celery hooks (e.g. an "auto-stamp
status=ABGEHALTEN once scheduled_end has passed" task).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgendaItemType,
    AssemblyStatus,
    Contact,
    Contract,
    ContractContact,
    Document,
    EtvAgendaItem,
    EtvAssembly,
    EtvDiscussionEntry,
    Property,
    User,
    UserRole,
)

logger = logging.getLogger(__name__)

# Only nudge owners about invitations whose issued_date (= a fresh
# stub's scheduled_start) is no older than this. Guards the very first
# production backfill from blasting a push for every historical ETV in
# the Impower archive — only genuinely-recent invitations notify, and
# the idempotent backfill means each one fires exactly once.
_INVITATION_NOTIFY_FRESHNESS_DAYS = 21

BERLIN_TZ = ZoneInfo("Europe/Berlin")

# Heuristic boundary between "definitely already happened" and
# "probably still upcoming / on the way". Invitations are typically
# sent 2-4 weeks before a Versammlung; anything older than this is
# extremely unlikely to still be in the future.
_ABGEHALTEN_THRESHOLD_DAYS = 60


def _now() -> datetime:
    return datetime.now(UTC)


async def load_assembly_for_org(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    assembly_id: uuid.UUID,
    include_deleted: bool = False,
) -> EtvAssembly | None:
    """Fetch one assembly inside the caller's organization.

    Returns the header row only. Agenda items + discussion are fetched
    by `load_agenda_items` + `load_discussion_for_items` so callers
    that only need the header (e.g. PATCH endpoints) don't pay for the
    full tree. The detail endpoint composes all three into the nested
    response.
    """
    assembly = await session.scalar(
        select(EtvAssembly).where(
            EtvAssembly.id == assembly_id,
            EtvAssembly.organization_id == organization_id,
        )
    )
    if assembly is None:
        return None
    if not include_deleted and assembly.deleted_at is not None:
        return None
    return assembly


async def load_agenda_items(
    session: AsyncSession,
    *,
    assembly_id: uuid.UUID,
) -> list[EtvAgendaItem]:
    rows = (
        await session.scalars(
            select(EtvAgendaItem)
            .where(EtvAgendaItem.assembly_id == assembly_id)
            .order_by(EtvAgendaItem.position)
        )
    ).all()
    return list(rows)


async def load_discussion_for_items(
    session: AsyncSession,
    *,
    agenda_item_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[EtvDiscussionEntry]]:
    """Returns {agenda_item_id: [entries ordered by position]}.

    One query for all items so the detail endpoint stays O(1) round-
    trips regardless of how many TOPs the assembly has.
    """
    if not agenda_item_ids:
        return {}
    rows = (
        await session.scalars(
            select(EtvDiscussionEntry)
            .where(EtvDiscussionEntry.agenda_item_id.in_(agenda_item_ids))
            .order_by(
                EtvDiscussionEntry.agenda_item_id,
                EtvDiscussionEntry.position,
            )
        )
    ).all()
    bucket: dict[uuid.UUID, list[EtvDiscussionEntry]] = {aid: [] for aid in agenda_item_ids}
    for r in rows:
        bucket[r.agenda_item_id].append(r)
    return bucket


async def list_assemblies_for_property(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    property_id: uuid.UUID,
    include_cancelled: bool = False,
) -> list[EtvAssembly]:
    """Property-scoped queue ordered newest-first by scheduled_start.

    The owner portal hides ABGESAGT; the admin queue can opt-in via
    include_cancelled=True.
    """
    stmt = (
        select(EtvAssembly)
        .where(
            EtvAssembly.organization_id == organization_id,
            EtvAssembly.property_id == property_id,
            EtvAssembly.deleted_at.is_(None),
        )
        .order_by(EtvAssembly.scheduled_start.desc())
    )
    if not include_cancelled:
        stmt = stmt.where(EtvAssembly.status != AssemblyStatus.ABGESAGT)
    rows = (await session.scalars(stmt)).all()
    return list(rows)


async def list_assemblies_for_org(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
) -> list[EtvAssembly]:
    """Verwalter cross-property queue."""
    rows = (
        await session.scalars(
            select(EtvAssembly)
            .where(
                EtvAssembly.organization_id == organization_id,
                EtvAssembly.deleted_at.is_(None),
            )
            .order_by(EtvAssembly.scheduled_start.desc())
        )
    ).all()
    return list(rows)


def compute_vote_result(item: EtvAgendaItem) -> str | None:
    """Convenience: derive ANGENOMMEN / ABGELEHNT for an item if it
    hasn't been explicitly set. Mirrors the Umlaufbeschluss rule:

      - INFORMATION / DISKUSSION → None (no vote, never a result)
      - BESCHLUSS with cast < required_quorum → ABGELEHNT
      - BESCHLUSS otherwise → ANGENOMMEN if yes > no else ABGELEHNT

    Used as a fallback display value; the admin can still override
    via `vote_result` for edge-cases (e.g. abstention rules in
    certain WEGs).
    """
    if item.type != AgendaItemType.BESCHLUSS:
        return None
    if item.vote_result is not None:
        return item.vote_result.value
    cast = item.vote_yes + item.vote_no + item.vote_abstain
    if item.vote_required_quorum is not None and cast < item.vote_required_quorum:
        return "ABGELEHNT"
    return "ANGENOMMEN" if item.vote_yes > item.vote_no else "ABGELEHNT"


async def backfill_assemblies_from_invitations(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    today: date | None = None,
) -> tuple[int, int, list[uuid.UUID]]:
    """One-off: create EtvAssembly stubs from existing Impower
    OWNERS_MEETING_INVITATION documents.

    Each (property_id, issued_date) group → one assembly. Idempotent:
    re-running skips groups that already have an assembly within ±1
    day of the invitation date (small fuzz to absorb manual data
    entry by the Verwalter who may have used the meeting date, not
    the invitation date).

    Returns (created, skipped_already_present, created_ids).

    `created_ids` is the list of assembly UUIDs created in this call.
    Callers that want LLM extraction (ADR-0008) commit first, then
    enqueue `extract_etv_metadata` Celery tasks against these IDs —
    the CLI's `--extract` flag does exactly that.

    Caveats baked into the stub:
      - `scheduled_start` uses the invitation's `issued_date` at 18:00
        Europe/Berlin. The actual meeting is usually 2-4 weeks later
        and lives inside the PDF body — the LLM extraction step
        corrects this when run.
      - `location` and `description` carry a "(bitte ergänzen)" hint
        so the inaccuracy is visible until extraction lands.
      - `status` falls to ABGEHALTEN once `issued_date` is older than
        ~60 days (any meeting that was being invited that long ago
        has almost certainly happened).
    """
    if today is None:
        today = date.today()

    # Step 1: load distinct (property_id, issued_date) from the
    # invitation documents the user actually has in this org.
    invite_groups_stmt = (
        select(Document.property_id, Document.issued_date)
        .where(
            Document.organization_id == organization_id,
            Document.impower_source_type == "OWNERS_MEETING_INVITATION",
            Document.deleted_at.is_(None),
            Document.property_id.is_not(None),
            Document.issued_date.is_not(None),
        )
        .group_by(Document.property_id, Document.issued_date)
    )
    rows = (await session.execute(invite_groups_stmt)).all()

    # Step 2: load existing assemblies in this org so we can short-
    # circuit groups that already have one. Using just (property_id,
    # date(scheduled_start)) as the dedup key — same fuzz as the
    # docstring promises.
    existing_stmt = select(EtvAssembly.property_id, func.date(EtvAssembly.scheduled_start)).where(
        EtvAssembly.organization_id == organization_id,
        EtvAssembly.deleted_at.is_(None),
    )
    existing_keys: set[tuple[uuid.UUID, date]] = set()
    for prop_id, dt in (await session.execute(existing_stmt)).all():
        existing_keys.add((prop_id, dt))

    created = 0
    skipped = 0
    created_ids: list[uuid.UUID] = []
    for property_id, issued_date in rows:
        # Slightly-fuzzy match: also treat ±1 day as "already exists"
        # so a Verwalter who manually entered the actual meeting date
        # (≈ invitation_date + 3 weeks) keeps theirs, not ours.
        clash = any(
            (property_id, d) in existing_keys
            for d in (
                issued_date,
                issued_date + timedelta(days=1),
                issued_date - timedelta(days=1),
            )
        )
        if clash:
            skipped += 1
            continue

        # Build the placeholder start/end timestamps. 18:00 Europe/
        # Berlin is the most common ETV slot; conversion to UTC at
        # write-time is transparent thanks to zoneinfo + the column's
        # `timezone=True`.
        start_berlin = datetime.combine(
            issued_date,
            time(hour=18, minute=0),
            tzinfo=BERLIN_TZ,
        )
        end_berlin = start_berlin + timedelta(hours=3)

        age_days = (today - issued_date).days
        status = (
            AssemblyStatus.ABGEHALTEN
            if age_days >= _ABGEHALTEN_THRESHOLD_DAYS
            else AssemblyStatus.EINGELADEN
        )

        assembly = EtvAssembly(
            organization_id=organization_id,
            property_id=property_id,
            title=f"Eigentümerversammlung {issued_date.year}",
            # Backfill creates a stub the Verwalter fills in via the
            # admin UI or LLM extraction; we leave description empty
            # so the owner portal doesn't show admin-noise like
            # "Automatisch aus Bestand übernommen …" to end users.
            description="",
            location="(noch nicht erfasst)",
            scheduled_start=start_berlin.astimezone(UTC),
            scheduled_end=end_berlin.astimezone(UTC),
            status=status,
        )
        session.add(assembly)
        await session.flush()  # populate assembly.id for the return list
        created_ids.append(assembly.id)
        created += 1

    return created, skipped, created_ids


async def resolve_assembly_comment_notification_recipients(
    session: AsyncSession,
    *,
    assembly: EtvAssembly,
    new_comment_id: uuid.UUID,
    new_author_user_id: uuid.UUID,
) -> list[User]:
    """Recipients for the "new comment on Versammlung X" email.

    Two sets, unioned + de-duped + minus the new commenter:
      - Every active VERWALTER in the assembly's org (always — the
        admin team owns the conversation; without this email the
        Verwalter would never notice new comments).
      - Every distinct prior commenter on the same assembly (thread
        participants — same reply-notification semantics as a forum
        thread).
    """
    from app.models import EtvAssemblyComment

    verwalter = (
        await session.scalars(
            select(User).where(
                User.organization_id == assembly.organization_id,
                User.role == UserRole.VERWALTER,
                User.deleted_at.is_(None),
                User.id != new_author_user_id,
            )
        )
    ).all()

    prior_author_ids = [
        row[0]
        for row in (
            await session.execute(
                select(EtvAssemblyComment.author_user_id)
                .where(
                    EtvAssemblyComment.assembly_id == assembly.id,
                    EtvAssemblyComment.id != new_comment_id,
                    EtvAssemblyComment.author_user_id != new_author_user_id,
                )
                .distinct()
            )
        ).all()
    ]

    prior_users: list[User] = []
    if prior_author_ids:
        prior_users = list(
            (
                await session.scalars(
                    select(User).where(
                        User.id.in_(prior_author_ids),
                        User.deleted_at.is_(None),
                    )
                )
            ).all()
        )

    seen: set[uuid.UUID] = set()
    merged: list[User] = []
    for u in [*verwalter, *prior_users]:
        if u.id in seen:
            continue
        seen.add(u.id)
        merged.append(u)
    return merged


async def resolve_assembly_invitation_recipients(
    session: AsyncSession,
    *,
    assembly: EtvAssembly,
) -> list[User]:
    """Recipients for the "new Einladung available" nudge on a freshly
    backfilled assembly.

    Two sets, unioned + de-duped:
      - Every active VERWALTER in the assembly's org (they own the ETV).
      - Every active EIGENTUEMER / BEIRAT linked to the assembly's
        property, resolved the same way the portal scopes property
        visibility: user.contact_id_impower → contacts → contract_contacts
        → contracts.property_id.

    MIETER (tenants) and DIENSTLEISTER are deliberately excluded — they
    are not invited to the Eigentümerversammlung, so pushing them an
    invitation would be wrong.
    """
    verwalter = (
        await session.scalars(
            select(User).where(
                User.organization_id == assembly.organization_id,
                User.role == UserRole.VERWALTER,
                User.deleted_at.is_(None),
            )
        )
    ).all()

    owners = (
        await session.scalars(
            select(User)
            .join(Contact, Contact.impower_id == User.contact_id_impower)
            .join(ContractContact, ContractContact.contact_id == Contact.id)
            .join(Contract, Contract.id == ContractContact.contract_id)
            .where(
                User.organization_id == assembly.organization_id,
                User.role.in_([UserRole.EIGENTUEMER, UserRole.BEIRAT]),
                User.deleted_at.is_(None),
                User.contact_id_impower.is_not(None),
                Contact.organization_id == assembly.organization_id,
                Contract.property_id == assembly.property_id,
            )
            .distinct()
        )
    ).all()

    seen: set[uuid.UUID] = set()
    merged: list[User] = []
    for u in [*verwalter, *owners]:
        if u.id in seen:
            continue
        seen.add(u.id)
        merged.append(u)
    return merged


async def notify_owners_of_new_invitations(
    session: AsyncSession,
    *,
    assembly_ids: list[uuid.UUID],
    email_client: object,
    freshness_days: int = _INVITATION_NOTIFY_FRESHNESS_DAYS,
) -> int:
    """Email + push each property's owners that a new ETV invitation is
    available, for the assembly stubs just created by
    `backfill_assemblies_from_invitations`.

    Best-effort and idempotent-friendly:
      - Skips deleted / ABGESAGT / ABGEHALTEN assemblies.
      - Skips anything whose `scheduled_start` (= the invitation's
        issued_date for a fresh stub) is older than `freshness_days`,
        so a first-run historical backfill doesn't spam owners about
        ETVs from years ago. Combined with the backfill's idempotency
        (only newly-created ids are passed in), each new invitation
        notifies exactly once.
      - Per-recipient email send; a single bad address or a disabled
        Resend key (EmailError) never sinks the batch. Push fans out
        to the same recipient set and no-ops when APNs is unconfigured.

    `email_client` is typed loosely (`object`) so this stays decoupled
    from the concrete EmailClient — the Celery worker and the CLI both
    hand in a live client; callers without one can pass a stub. Returns
    the number of assemblies that triggered a notification.
    """
    if not assembly_ids:
        return 0

    from app.integrations.email.client import EmailError
    from app.integrations.email.etv import render_assembly_invitation_notification_email
    from app.models import NotificationCategory, NotificationChannel
    from app.services import notification_prefs, push

    cutoff = _now() - timedelta(days=freshness_days)
    notified = 0
    for assembly_id in assembly_ids:
        try:
            assembly = await session.get(EtvAssembly, assembly_id)
            if assembly is None or assembly.deleted_at is not None:
                continue
            if assembly.status in (AssemblyStatus.ABGEHALTEN, AssemblyStatus.ABGESAGT):
                continue
            if assembly.scheduled_start < cutoff:
                continue

            recipients = await resolve_assembly_invitation_recipients(session, assembly=assembly)
            if not recipients:
                continue

            # Honour each recipient's notification preferences: only
            # email the users who haven't disabled ETV_INVITATION email,
            # and only push to those who haven't disabled its push.
            recipient_ids = [r.id for r in recipients]
            email_ok = set(
                await notification_prefs.filter_user_ids(
                    session,
                    user_ids=recipient_ids,
                    category=NotificationCategory.ETV_INVITATION,
                    channel=NotificationChannel.EMAIL,
                )
            )
            push_ids = await notification_prefs.filter_user_ids(
                session,
                user_ids=recipient_ids,
                category=NotificationCategory.ETV_INVITATION,
                channel=NotificationChannel.PUSH,
            )

            prop = await session.get(Property, assembly.property_id)
            property_name = prop.name if prop else "—"
            subject, html_body, text_body = render_assembly_invitation_notification_email(
                assembly_id=str(assembly.id),
                assembly_title=assembly.title,
                property_name=property_name,
            )
            for r in recipients:
                if not r.email or r.id not in email_ok:
                    continue
                try:
                    await email_client.send(  # type: ignore[attr-defined]
                        to=r.email,
                        subject=subject,
                        html=html_body,
                        text=text_body,
                    )
                except EmailError:
                    logger.warning(
                        "ETV invitation email failed for %s (assembly=%s)",
                        r.email,
                        assembly.id,
                    )

            await push.notify_users(
                session,
                user_ids=push_ids,
                title="Neue Einladung zur Eigentümerversammlung",
                body=f"{property_name}: {assembly.title}",
                deep_link=f"whv://etv/{assembly.id}",
                thread_id=f"etv-{assembly.id}",
            )
            notified += 1
        except Exception:
            # One assembly's notification failing must not stop the rest
            # nor fail the surrounding sync task.
            logger.exception(
                "ETV invitation notify fan-out failed for assembly=%s",
                assembly_id,
            )
    return notified


def require_verwalter(user: User) -> None:
    """Raise ValueError if the user isn't a Verwalter. Endpoints catch
    this and translate to HTTP 403 — keeping the check in a helper
    means the same gate covers all the admin-only mutation paths
    (agenda items, discussion, protocol upload) without ten copies."""
    if user.role != UserRole.VERWALTER:
        raise ValueError("Verwalter role required")
