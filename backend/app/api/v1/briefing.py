"""Objekt-Briefing for the car — `GET /me/properties/{id}/briefing` (Verwalter).

A deterministic 20-40 second German summary the app reads aloud (AVSpeech
over the car speakers) before the Verwalter walks in: open tickets, today's /
next appointments, last + next ETV, Zähler due, Jahresabrechnung progress,
contacts on site. No LLM: it must be instant, cheap and say the same thing
every time; free questions stay with "Frag WHV".
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db import get_session
from app.models import (
    AssemblyStatus,
    Contact,
    Contract,
    ContractContact,
    EtvAssembly,
    Meter,
    MeterReading,
    Property,
    Ticket,
    TicketStatus,
    User,
    UserRole,
)
from app.services import calendar as calendar_svc
from app.services.access import active_property_filter
from app.services.accounting import active_accounting_year, get_progress
from app.services.activity import METER_DUE_LOOKAHEAD_DAYS

me_router = APIRouter(prefix="/me", tags=["briefing"])
_verwalter_only = require_role(UserRole.VERWALTER)
_BERLIN = ZoneInfo("Europe/Berlin")

_TYPE_LABEL = {"OWNER": "WEG", "RENTAL": "Mietverwaltung", "STRATA": "SEV"}


class BriefingSection(BaseModel):
    title: str
    lines: list[str]


class BriefingResponse(BaseModel):
    property_id: uuid.UUID
    property_name: str
    # Ready-to-speak German (full sentences, no abbreviations/symbols).
    spoken: str
    sections: list[BriefingSection]
    generated_at: datetime


_MONTHS = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]  # fmt: skip


def _spoken_date(d: date | datetime, today: date) -> str:
    dd = d.astimezone(_BERLIN).date() if isinstance(d, datetime) else d
    if dd == today:
        return "heute"
    if dd == today + timedelta(days=1):
        return "morgen"
    if dd == today - timedelta(days=1):
        return "gestern"
    return f"am {dd.day}. {_MONTHS[dd.month - 1]}"


def _spoken_time(d: datetime) -> str:
    loc = d.astimezone(_BERLIN)
    return f"{loc.hour} Uhr" if loc.minute == 0 else f"{loc.hour} Uhr {loc.minute:02d}"


def _n(count: int, one: str, many: str) -> str:
    return f"ein {one}" if count == 1 else f"{count} {many}"


@me_router.get("/properties/{property_id}/briefing", response_model=BriefingResponse)
async def property_briefing(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BriefingResponse:
    prop = await session.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.organization_id == current_user.organization_id,
            active_property_filter(),
        )
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Objekt nicht gefunden")

    org_id = current_user.organization_id
    now = datetime.now(UTC)
    today = now.astimezone(_BERLIN).date()
    sections: list[BriefingSection] = []
    spoken: list[str] = []

    # --- Kopf ------------------------------------------------------------
    type_label = _TYPE_LABEL.get(prop.type.value, prop.type.value)
    units = await session.scalar(
        select(func.count())
        .select_from(Contract)
        .where(Contract.property_id == prop.id, Contract.deleted_at.is_(None))
    )
    # Names already carry "WEG …" / "MV …" / "SEV …" — don't say it twice.
    spoken.append(f"Briefing {prop.name.split(',')[0].strip()}.")

    # --- Tickets ---------------------------------------------------------
    open_tickets = list(
        (
            await session.scalars(
                select(Ticket)
                .where(
                    Ticket.organization_id == org_id,
                    Ticket.property_id == prop.id,
                    Ticket.status != TicketStatus.GESCHLOSSEN,
                )
                .order_by(Ticket.last_message_at.desc(), Ticket.created_at.desc())
            )
        ).all()
    )
    if open_tickets:
        top = [t.subject for t in open_tickets[:3]]
        sections.append(BriefingSection(title=f"Offene Tickets ({len(open_tickets)})", lines=top))
        spoken.append(
            f"{_n(len(open_tickets), 'offenes Ticket', 'offene Tickets')}: " + "; ".join(top) + "."
        )
    else:
        sections.append(BriefingSection(title="Offene Tickets", lines=["keine"]))
        spoken.append("Keine offenen Tickets.")

    # --- Termine (heute + nächste 14 Tage) --------------------------------
    agenda = await calendar_svc.agenda(
        session,
        organization_id=org_id,
        from_day=today,
        to_day=today + timedelta(days=14),
        property_id=prop.id,
    )
    if agenda:
        lines = []
        for a in agenda[:3]:
            when = _spoken_date(a.starts_at, today)
            if not a.all_day:
                when += f" um {_spoken_time(a.starts_at)}"
            lines.append(f"{a.title} {when}")
        sections.append(BriefingSection(title="Termine", lines=lines))
        spoken.append("Termine: " + "; ".join(lines) + ".")
    else:
        spoken.append("Keine Termine in den nächsten zwei Wochen.")

    # --- ETV: letzte + nächste ---------------------------------------------
    last_etv = await session.scalar(
        select(EtvAssembly)
        .where(
            EtvAssembly.organization_id == org_id,
            EtvAssembly.property_id == prop.id,
            EtvAssembly.deleted_at.is_(None),
            EtvAssembly.status != AssemblyStatus.ABGESAGT,
            EtvAssembly.scheduled_start < now,
        )
        .order_by(EtvAssembly.scheduled_start.desc())
        .limit(1)
    )
    next_etv = await session.scalar(
        select(EtvAssembly)
        .where(
            EtvAssembly.organization_id == org_id,
            EtvAssembly.property_id == prop.id,
            EtvAssembly.deleted_at.is_(None),
            EtvAssembly.status != AssemblyStatus.ABGESAGT,
            EtvAssembly.scheduled_start >= now,
        )
        .order_by(EtvAssembly.scheduled_start.asc())
        .limit(1)
    )
    etv_lines: list[str] = []
    if last_etv is not None:
        etv_lines.append(f"Letzte Versammlung {_spoken_date(last_etv.scheduled_start, today)}")
    if next_etv is not None:
        etv_lines.append(
            f"Nächste Versammlung {_spoken_date(next_etv.scheduled_start, today)} "
            f"um {_spoken_time(next_etv.scheduled_start)}"
        )
    if type_label == "WEG":
        if etv_lines:
            sections.append(BriefingSection(title="Eigentümerversammlung", lines=etv_lines))
            spoken.append(". ".join(etv_lines) + ".")
        else:
            spoken.append("Für dieses Jahr ist noch keine Eigentümerversammlung geplant.")

    # --- Zähler fällig ------------------------------------------------------
    due_horizon = today + timedelta(days=METER_DUE_LOOKAHEAD_DAYS)
    due_meters = list(
        (
            await session.scalars(
                select(Meter).where(
                    Meter.organization_id == org_id,
                    Meter.property_id == prop.id,
                    Meter.is_active.is_(True),
                    Meter.reading_due_date.is_not(None),
                    Meter.reading_due_date <= due_horizon,
                )
            )
        ).all()
    )
    if due_meters:
        read_since = [m.reading_due_date for m in due_meters if m.reading_due_date]
        earliest = min(read_since) if read_since else None
        # A reading on/after the due date's quarter start counts as done.
        pending = 0
        for m in due_meters:
            quarter_start = (m.reading_due_date or today) - timedelta(days=89)
            has = await session.scalar(
                select(func.count())
                .select_from(MeterReading)
                .where(MeterReading.meter_id == m.id, MeterReading.read_on >= quarter_start)
            )
            if not has:
                pending += 1
        if pending:
            sections.append(
                BriefingSection(
                    title="Zähler",
                    lines=[
                        f"{pending} Ablesung(en) fällig"
                        + (f" bis {_spoken_date(earliest, today)}" if earliest else "")
                    ],
                )
            )
            spoken.append(f"{_n(pending, 'Zählerablesung', 'Zählerablesungen')} fällig.")

    # --- Jahresabrechnung ----------------------------------------------------
    year = active_accounting_year(today)
    progress = await get_progress(session, property_id=prop.id, year=year)
    sections.append(
        BriefingSection(
            title=f"Jahresabrechnung {year}",
            lines=[f"{progress.done_count} von {progress.total} Schritten erledigt"],
        )
    )
    if progress.done_count >= progress.total:
        spoken.append(f"Jahresabrechnung {year} ist fertig.")
    else:
        spoken.append(
            f"Jahresabrechnung {year}: {progress.done_count} von {progress.total} "
            "Schritten erledigt."
        )

    # --- Kontakte vor Ort ----------------------------------------------------
    contacts = (
        await session.execute(
            select(Contact, Contract.type)
            .join(ContractContact, ContractContact.contact_id == Contact.id)
            .join(Contract, Contract.id == ContractContact.contract_id)
            .where(
                Contract.property_id == prop.id,
                Contract.deleted_at.is_(None),
                Contact.deleted_at.is_(None),
                or_(Contract.end_date.is_(None), Contract.end_date >= today),
            )
        )
    ).all()
    owners = len({c.id for c, t in contacts if t.value in ("OWNER", "PROPERTY_OWNER")})
    tenants = len({c.id for c, t in contacts if t.value == "TENANT"})
    head = []
    if units:
        head.append(f"{units} Verträge")
    if owners:
        head.append(_n(owners, "Eigentümer", "Eigentümer"))
    if tenants:
        head.append(_n(tenants, "Mieter", "Mieter"))
    if head:
        sections.insert(0, BriefingSection(title="Objekt", lines=[", ".join(head)]))

    return BriefingResponse(
        property_id=prop.id,
        property_name=prop.name,
        spoken=" ".join(spoken),
        sections=sections,
        generated_at=now,
    )
