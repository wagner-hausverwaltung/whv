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

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgendaItemType,
    AssemblyStatus,
    Document,
    EtvAgendaItem,
    EtvAssembly,
    EtvDiscussionEntry,
    User,
    UserRole,
)

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
    bucket: dict[uuid.UUID, list[EtvDiscussionEntry]] = {
        aid: [] for aid in agenda_item_ids
    }
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
    existing_stmt = (
        select(EtvAssembly.property_id, func.date(EtvAssembly.scheduled_start))
        .where(
            EtvAssembly.organization_id == organization_id,
            EtvAssembly.deleted_at.is_(None),
        )
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
            description=(
                "Automatisch aus Bestand übernommen. "
                "Bitte Datum, Ort und Tagesordnung prüfen."
            ),
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


def require_verwalter(user: User) -> None:
    """Raise ValueError if the user isn't a Verwalter. Endpoints catch
    this and translate to HTTP 403 — keeping the check in a helper
    means the same gate covers all the admin-only mutation paths
    (agenda items, discussion, protocol upload) without ten copies."""
    if user.role != UserRole.VERWALTER:
        raise ValueError("Verwalter role required")
