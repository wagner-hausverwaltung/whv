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
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgendaItemType,
    AssemblyStatus,
    EtvAgendaItem,
    EtvAssembly,
    EtvDiscussionEntry,
    User,
    UserRole,
)


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


def require_verwalter(user: User) -> None:
    """Raise ValueError if the user isn't a Verwalter. Endpoints catch
    this and translate to HTTP 403 — keeping the check in a helper
    means the same gate covers all the admin-only mutation paths
    (agenda items, discussion, protocol upload) without ten copies."""
    if user.role != UserRole.VERWALTER:
        raise ValueError("Verwalter role required")
