"""Liegenschafts-Kalender service (ADR-0018).

CRUD for stored events + a merged read view that folds in ETV dates derived
live from etv_assemblies (so they never drift). PDF rendering uses
`render_calendar_pdf`.
"""

from __future__ import annotations

import uuid
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.pdf.calendar_document import CalendarPdfEntry
from app.models import (
    AssemblyStatus,
    AuditLog,
    CalendarEvent,
    CalendarEventType,
    EtvAssembly,
)
from app.schemas.calendar import CalendarEntry, CalendarEventCreate, CalendarEventUpdate

_BERLIN = ZoneInfo("Europe/Berlin")

_DEFAULT_TITLE = {
    CalendarEventType.WINTERDIENST: "Winterdienst",
    CalendarEventType.KEHRWOCHE: "Kehrwoche",
    CalendarEventType.TERMIN: "Termin",
}


class CalendarServiceError(ValueError):
    """Validation error mapped to HTTP 400 by the endpoints."""


def _title(event: CalendarEvent) -> str:
    return event.title or _DEFAULT_TITLE.get(event.event_type, "Termin")


async def export_source(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    property_id: uuid.UUID,
) -> tuple[list[EtvAssembly], list[CalendarEvent]]:
    """All ETV assemblies + stored events for a property — the source for the
    .ics export. No date window: the export carries everything and the client's
    calendar dedups/updates by UID on re-import."""
    assemblies = list(
        await session.scalars(
            select(EtvAssembly)
            .where(
                EtvAssembly.organization_id == organization_id,
                EtvAssembly.property_id == property_id,
                EtvAssembly.deleted_at.is_(None),
            )
            .order_by(EtvAssembly.scheduled_start)
        )
    )
    events = list(
        await session.scalars(
            select(CalendarEvent)
            .where(
                CalendarEvent.organization_id == organization_id,
                CalendarEvent.property_id == property_id,
            )
            .order_by(CalendarEvent.starts_on)
        )
    )
    return assemblies, events


# --- CRUD --------------------------------------------------------------------


async def create_event(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    property_id: uuid.UUID,
    actor_id: uuid.UUID,
    data: CalendarEventCreate,
) -> CalendarEvent:
    if data.ends_on is not None and data.ends_on < data.starts_on:
        raise CalendarServiceError("Das Enddatum liegt vor dem Startdatum.")
    event = CalendarEvent(
        organization_id=organization_id,
        property_id=property_id,
        event_type=data.event_type,
        title=(data.title.strip() if data.title and data.title.strip() else None),
        starts_on=data.starts_on,
        ends_on=data.ends_on,
        assigned_user_id=data.assigned_user_id,
        assigned_label=(data.assigned_label.strip() if data.assigned_label else None),
        note=(data.note.strip() if data.note else None),
        created_by_user_id=actor_id,
    )
    session.add(event)
    await session.flush()
    session.add(
        AuditLog(
            organization_id=organization_id,
            actor_user_id=actor_id,
            action="calendar_event_created",
            target_type="calendar_events",
            target_id=str(event.id),
            payload_json={
                "property_id": str(property_id),
                "type": event.event_type.value,
                "starts_on": event.starts_on.isoformat(),
            },
        )
    )
    await session.commit()
    await session.refresh(event)
    return event


async def update_event(
    session: AsyncSession,
    *,
    event: CalendarEvent,
    actor_id: uuid.UUID,
    data: CalendarEventUpdate,
) -> CalendarEvent:
    changes = data.model_dump(exclude_unset=True)
    new_start = changes.get("starts_on", event.starts_on)
    new_end = changes.get("ends_on", event.ends_on)
    if new_end is not None and new_end < new_start:
        raise CalendarServiceError("Das Enddatum liegt vor dem Startdatum.")
    for field, value in changes.items():
        if field in {"title", "assigned_label", "note"} and isinstance(value, str):
            value = value.strip() or None
        setattr(event, field, value)
    session.add(
        AuditLog(
            organization_id=event.organization_id,
            actor_user_id=actor_id,
            action="calendar_event_updated",
            target_type="calendar_events",
            target_id=str(event.id),
            payload_json={"fields": sorted(changes.keys())},
        )
    )
    await session.commit()
    await session.refresh(event)
    return event


async def delete_event(session: AsyncSession, *, event: CalendarEvent, actor_id: uuid.UUID) -> None:
    org_id = event.organization_id
    eid = event.id
    await session.delete(event)
    session.add(
        AuditLog(
            organization_id=org_id,
            actor_user_id=actor_id,
            action="calendar_event_deleted",
            target_type="calendar_events",
            target_id=str(eid),
            payload_json={},
        )
    )
    await session.commit()


async def get_event(
    session: AsyncSession, *, event_id: uuid.UUID, organization_id: uuid.UUID
) -> CalendarEvent | None:
    result: CalendarEvent | None = await session.scalar(
        select(CalendarEvent).where(
            CalendarEvent.id == event_id,
            CalendarEvent.organization_id == organization_id,
        )
    )
    return result


# --- merged view -------------------------------------------------------------


async def merged_entries(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    property_id: uuid.UUID,
    range_start: date,
    range_end: date,
) -> list[CalendarEntry]:
    """Stored events overlapping [range_start, range_end] + ETV dates derived
    from the property's assemblies in that window, sorted by start date."""
    out: list[CalendarEntry] = []

    event_rows = (
        await session.scalars(
            select(CalendarEvent)
            .where(
                CalendarEvent.organization_id == organization_id,
                CalendarEvent.property_id == property_id,
                CalendarEvent.starts_on <= range_end,
                func.coalesce(CalendarEvent.ends_on, CalendarEvent.starts_on) >= range_start,
            )
            .order_by(CalendarEvent.starts_on)
        )
    ).all()
    for e in event_rows:
        out.append(
            CalendarEntry(
                kind=e.event_type.value,
                source="event",
                id=e.id,
                title=_title(e),
                starts_on=e.starts_on,
                ends_on=e.ends_on,
                assigned_user_id=e.assigned_user_id,
                assigned_label=e.assigned_label,
                note=e.note,
            )
        )

    assembly_rows = (
        await session.scalars(
            select(EtvAssembly).where(
                EtvAssembly.organization_id == organization_id,
                EtvAssembly.property_id == property_id,
                EtvAssembly.deleted_at.is_(None),
                EtvAssembly.status != AssemblyStatus.ABGESAGT,
            )
        )
    ).all()
    for a in assembly_rows:
        if a.scheduled_start is None:
            continue
        day = a.scheduled_start.astimezone(_BERLIN).date()
        if range_start <= day <= range_end:
            out.append(
                CalendarEntry(
                    kind="ETV",
                    source="etv",
                    id=a.id,
                    title=a.title,
                    starts_on=day,
                    ends_on=None,
                    assembly_id=a.id,
                )
            )

    out.sort(key=lambda x: (x.starts_on, x.kind))
    return out


def to_pdf_entries(entries: list[CalendarEntry]) -> list[CalendarPdfEntry]:
    return [
        CalendarPdfEntry(
            kind=e.kind,
            title=e.title,
            starts_on=e.starts_on,
            ends_on=e.ends_on,
            assigned=e.assigned_label,
        )
        for e in entries
    ]
