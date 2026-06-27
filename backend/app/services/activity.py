"""Unified portal activity feed (the "Was gibt's Neues" surface).

Aggregates recent + actionable events across every Liegenschaft a portal
user (Eigentümer / Mieter / Beirat / Verwalter) can see, into one
ready-sorted list. The iOS home-screen widget calls `/me/activity` once
and renders the result top-to-bottom, so all the ranking happens here.

ACL is NOT re-implemented in this module: the API layer resolves the
visible-property set + the document/invoice row-scope filters with the
exact same primitives every other `/me` endpoint uses
(`_visible_properties_stmt`, `_document_visibility_filter`,
`_invoice_visibility_filter`) and hands them in. This keeps `app.services`
free of an `app.api` import (which would be circular) while still binding
every query to the caller's scope. The only ACL rule resolved *inside*
this module is the OWNER-only eligibility for Beschlüsse — and that reuses
the same active-OWNER-contract test the circular API uses, constrained to
the already-visible property ids.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CalendarEvent,
    CalendarEventType,
    CircularResolution,
    Contact,
    Contract,
    ContractContact,
    ContractType,
    Document,
    DocumentKind,
    EtvAssembly,
    EtvAssemblyComment,
    Meter,
    MeterReading,
    Property,
    ResolutionStatus,
    User,
    UserRole,
)
from app.services import announcements as announcements_svc
from app.services.access import active_contract_filter
from app.services.meters import quarter_start

_BERLIN = ZoneInfo("Europe/Berlin")

# --- Recency / look-ahead windows (module-level so they're easy to tune) ---
# "New" items (documents, invoices, announcements, ETV comments, fresh
# invitations, decided Beschlüsse) only show up if their recency timestamp
# is within the last N days.
RECENT_WINDOW_DAYS = 30
# Upcoming ETV / calendar entries within the next N days (plus anything
# happening / in-progress now) make the feed.
UPCOMING_WINDOW_DAYS = 30
# A Zählerstand reminder fires once the due date is within N days ahead
# (or already overdue).
METER_DUE_LOOKAHEAD_DAYS = 45


class ActivityType(enum.StrEnum):
    RESOLUTION = "RESOLUTION"
    ETV = "ETV"
    ETV_COMMENT = "ETV_COMMENT"
    DOCUMENT = "DOCUMENT"
    INVOICE = "INVOICE"
    ANNOUNCEMENT = "ANNOUNCEMENT"
    CALENDAR = "CALENDAR"
    METER_DUE = "METER_DUE"


# Lower = more urgent = nearer the top. Deadline-driven items first.
_PRIORITY: dict[ActivityType, int] = {
    ActivityType.METER_DUE: 0,
    ActivityType.RESOLUTION: 0,
    ActivityType.ETV: 1,
    ActivityType.DOCUMENT: 2,
    ActivityType.INVOICE: 3,
    ActivityType.ANNOUNCEMENT: 4,
    ActivityType.ETV_COMMENT: 5,
    ActivityType.CALENDAR: 6,
}


class ActivityItem(BaseModel):
    """One feed row. Doubles as the `/me/activity` response item."""

    type: ActivityType
    id: str
    title: str
    subtitle: str
    timestamp: datetime
    priority: int
    property_id: uuid.UUID
    property_name: str | None
    deep_link: str


def _as_aware(dt: datetime) -> datetime:
    """Treat naive timestamps as UTC so comparisons never raise."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _fmt_date(d: date) -> str:
    return d.strftime("%d.%m.%Y")


async def _owner_visible_property_ids(
    session: AsyncSession,
    *,
    user: User,
    property_ids: list[uuid.UUID],
) -> set[uuid.UUID]:
    """Of the already-visible property ids, the subset on which the caller
    holds an *active OWNER* contract — i.e. is stimmberechtigt for
    Beschlüsse. Mirrors `circular._eligible_owner_impower_ids`' OWNER rule
    so a Mieter never sees a resolution.

    VERWALTER aren't owners of anything, but they administer every
    Beschluss in their org, so they see all of them on the visible set.
    """
    if not property_ids:
        return set()
    if user.role == UserRole.VERWALTER:
        return set(property_ids)
    if user.contact_id_impower is None:
        return set()
    rows = (
        await session.scalars(
            select(Property.id)
            .join(Contract, Contract.property_id == Property.id)
            .join(ContractContact, ContractContact.contract_id == Contract.id)
            .join(Contact, Contact.id == ContractContact.contact_id)
            .where(
                Property.id.in_(property_ids),
                Contract.type == ContractType.OWNER,
                Contract.deleted_at.is_(None),
                Contact.impower_id == user.contact_id_impower,
                Contact.deleted_at.is_(None),
                active_contract_filter(),
            )
            .distinct()
        )
    ).all()
    return set(rows)


async def build_activity_feed(
    session: AsyncSession,
    *,
    user: User,
    property_rows: list[Property],
    doc_filter: object,
    invoice_filter: object,
    today: date,
    now: datetime,
    limit: int,
) -> list[ActivityItem]:
    """Assemble + rank the caller's unified feed.

    `property_rows` is the ACL-resolved visible-Property set (caller built
    it via `_visible_properties_stmt`). `doc_filter` / `invoice_filter` are
    the SQLAlchemy row-scope expressions from `_document_visibility_filter`
    / `_invoice_visibility_filter`. Every query below is constrained to
    `property_ids` (∴ never crosses a property boundary) and, where the
    underlying data is per-owner/per-unit, ANDs in the supplied filter or
    the OWNER-eligibility subset.
    """
    now = _as_aware(now)
    property_ids = [p.id for p in property_rows]
    names: dict[uuid.UUID, str] = {p.id: p.name for p in property_rows}
    items: list[ActivityItem] = []
    if not property_ids:
        return []

    recent_cutoff = now - timedelta(days=RECENT_WINDOW_DAYS)
    upcoming_cutoff = now + timedelta(days=UPCOMING_WINDOW_DAYS)
    is_verwalter = user.role == UserRole.VERWALTER

    # --- RESOLUTION (Beschluss) — OWNER-only -----------------------------
    # Scope: property_ids ∩ active-OWNER-contract subset (Mieter excluded).
    # We surface OFFEN resolutions (deadline-driven, highest priority).
    owner_pids = await _owner_visible_property_ids(session, user=user, property_ids=property_ids)
    if owner_pids:
        res_rows = (
            await session.scalars(
                select(CircularResolution).where(
                    CircularResolution.organization_id == user.organization_id,
                    CircularResolution.property_id.in_(owner_pids),
                    CircularResolution.status == ResolutionStatus.OFFEN,
                )
            )
        ).all()
        for r in res_rows:
            closes = _as_aware(r.closes_at)
            items.append(
                ActivityItem(
                    type=ActivityType.RESOLUTION,
                    id=str(r.id),
                    title=r.title,
                    subtitle=f"Beschluss — Frist bis {_fmt_date(closes.date())}",
                    # Sort by the deadline: the soonest-closing Frist floats up.
                    timestamp=closes,
                    priority=_PRIORITY[ActivityType.RESOLUTION],
                    property_id=r.property_id,
                    property_name=names.get(r.property_id),
                    deep_link=f"whv://resolution/{r.id}",
                )
            )

    # --- ETV (upcoming / in-progress + fresh invitation) -----------------
    # Scope: assemblies on a visible property only (property_id constraint).
    etv_rows = (
        await session.scalars(
            select(EtvAssembly).where(
                EtvAssembly.organization_id == user.organization_id,
                EtvAssembly.property_id.in_(property_ids),
                EtvAssembly.deleted_at.is_(None),
            )
        )
    ).all()
    for a in etv_rows:
        start = _as_aware(a.scheduled_start)
        end = _as_aware(a.scheduled_end)
        inv_at = _as_aware(a.invitation_uploaded_at) if a.invitation_uploaded_at else None
        # Upcoming or currently-running assembly.
        if now <= end and start <= upcoming_cutoff:
            when = _fmt_date(start.astimezone(_BERLIN).date())
            in_progress = start <= now <= end
            subtitle = (
                "Eigentümerversammlung läuft" if in_progress else f"Eigentümerversammlung am {when}"
            )
            items.append(
                ActivityItem(
                    type=ActivityType.ETV,
                    id=str(a.id),
                    title=a.title,
                    subtitle=subtitle,
                    timestamp=start,
                    priority=_PRIORITY[ActivityType.ETV],
                    property_id=a.property_id,
                    property_name=names.get(a.property_id),
                    deep_link=f"whv://etv/{a.id}",
                )
            )
        # A freshly-uploaded invitation for an assembly that's NOT already
        # surfaced as upcoming (e.g. one further out than the window).
        elif inv_at is not None and inv_at >= recent_cutoff:
            when = _fmt_date(start.astimezone(_BERLIN).date())
            items.append(
                ActivityItem(
                    type=ActivityType.ETV,
                    id=str(a.id),
                    title=a.title,
                    subtitle=f"Neue Einladung — Versammlung am {when}",
                    timestamp=inv_at,
                    priority=_PRIORITY[ActivityType.ETV],
                    property_id=a.property_id,
                    property_name=names.get(a.property_id),
                    deep_link=f"whv://etv/{a.id}",
                )
            )

    # --- ETV_COMMENT -----------------------------------------------------
    # Scope: comments only on assemblies of visible properties (join ETV →
    # property_id constraint). Recent comments by anyone but the caller.
    comment_rows = (
        await session.execute(
            select(EtvAssemblyComment, EtvAssembly)
            .join(EtvAssembly, EtvAssembly.id == EtvAssemblyComment.assembly_id)
            .where(
                EtvAssembly.organization_id == user.organization_id,
                EtvAssembly.property_id.in_(property_ids),
                EtvAssembly.deleted_at.is_(None),
                EtvAssemblyComment.created_at >= recent_cutoff,
                EtvAssemblyComment.author_user_id != user.id,
            )
        )
    ).all()
    for c, a in comment_rows:
        created = _as_aware(c.created_at)
        items.append(
            ActivityItem(
                type=ActivityType.ETV_COMMENT,
                id=str(c.id),
                title=a.title,
                subtitle="Neuer Kommentar zur Eigentümerversammlung",
                timestamp=created,
                priority=_PRIORITY[ActivityType.ETV_COMMENT],
                property_id=a.property_id,
                property_name=names.get(a.property_id),
                deep_link=f"whv://etv/{a.id}",
            )
        )

    # --- DOCUMENT + INVOICE ---------------------------------------------
    # Scope: property_id constraint + the supplied row-scope filter.
    # Verwalter sees everything → skip the per-row filter (matching the
    # other /me endpoints). Recency = notified_at, fallback last_synced_at.
    doc_stmt = select(Document).where(
        Document.organization_id == user.organization_id,
        Document.property_id.in_(property_ids),
        Document.deleted_at.is_(None),
    )
    if not is_verwalter:
        # INVOICE filter is the superset (document filter OR WEG-RECHNUNG),
        # so a single pass with it covers both DOCUMENT and INVOICE rows.
        doc_stmt = doc_stmt.where(invoice_filter)  # type: ignore[arg-type]
    doc_rows = (await session.scalars(doc_stmt)).all()
    for d in doc_rows:
        recency = d.notified_at or d.last_synced_at
        if recency is None:
            continue
        recency = _as_aware(recency)
        if recency < recent_cutoff:
            continue
        is_invoice = d.kind == DocumentKind.RECHNUNG
        if is_invoice:
            atype = ActivityType.INVOICE
            subtitle = "Neue Rechnung verfügbar"
            deep_link = f"whv://invoice/{d.id}"
        else:
            atype = ActivityType.DOCUMENT
            subtitle = "Neues Dokument verfügbar"
            deep_link = f"whv://document/{d.id}"
        if d.property_id is None:  # defensive; the IN-filter already excludes NULL
            continue
        items.append(
            ActivityItem(
                type=atype,
                id=str(d.id),
                title=d.name,
                subtitle=subtitle,
                timestamp=recency,
                priority=_PRIORITY[atype],
                property_id=d.property_id,
                property_name=names.get(d.property_id),
                deep_link=deep_link,
            )
        )

    # --- ANNOUNCEMENT (Mitteilung) --------------------------------------
    # Scope: the service helper is already audience+ACL scoped per property;
    # we only call it for properties already in the visible set, so it can
    # never reach across a boundary. Recency = notification_sent_at.
    for pid in property_ids:
        anns, _ = await announcements_svc.list_for_property_owner(
            session, user=user, property_id=pid, limit=limit, offset=0
        )
        for ann in anns:
            sent = ann.notification_sent_at
            if sent is None:
                continue
            sent = _as_aware(sent)
            if sent < recent_cutoff:
                continue
            items.append(
                ActivityItem(
                    type=ActivityType.ANNOUNCEMENT,
                    id=str(ann.id),
                    title=ann.title,
                    subtitle="Neue Mitteilung",
                    timestamp=sent,
                    priority=_PRIORITY[ActivityType.ANNOUNCEMENT],
                    property_id=ann.property_id,
                    property_name=names.get(ann.property_id),
                    deep_link=f"whv://announcement/{ann.id}",
                )
            )

    # --- CALENDAR (upcoming Termine / Winterdienst / Kehrwoche) ----------
    # Scope: stored calendar events on visible properties only (we exclude
    # ETV-source entries here — those are already covered by the ETV pass).
    cal_rows = (
        await session.scalars(
            select(CalendarEvent).where(
                CalendarEvent.organization_id == user.organization_id,
                CalendarEvent.property_id.in_(property_ids),
                CalendarEvent.starts_on >= today,
                CalendarEvent.starts_on <= upcoming_cutoff.astimezone(_BERLIN).date(),
            )
        )
    ).all()
    _cal_titles = {
        CalendarEventType.WINTERDIENST: "Winterdienst",
        CalendarEventType.KEHRWOCHE: "Kehrwoche",
        CalendarEventType.TERMIN: "Termin",
    }
    for e in cal_rows:
        title = e.title or _cal_titles.get(e.event_type, "Termin")
        # Sort by the event date at Berlin noon so same-day items have a
        # stable, timezone-correct ordering relative to the other types.
        ts = datetime.combine(e.starts_on, datetime.min.time(), tzinfo=_BERLIN).astimezone(UTC)
        items.append(
            ActivityItem(
                type=ActivityType.CALENDAR,
                id=str(e.id),
                title=title,
                subtitle=f"Termin am {_fmt_date(e.starts_on)}",
                timestamp=ts,
                priority=_PRIORITY[ActivityType.CALENDAR],
                property_id=e.property_id,
                property_name=names.get(e.property_id),
                deep_link=f"whv://calendar/{e.id}",
            )
        )

    # --- METER_DUE (Zählerstand erfassen) --------------------------------
    # Scope: meters on visible properties only. Fires when reading_due_date
    # is set, within the look-ahead (or overdue), AND no reading exists for the
    # current quarter yet (capturing one anytime in the quarter clears it —
    # reading_due_date carries the quarter's end, set by the daily roll task).
    due_horizon = today + timedelta(days=METER_DUE_LOOKAHEAD_DAYS)
    meter_rows = (
        await session.scalars(
            select(Meter).where(
                Meter.organization_id == user.organization_id,
                Meter.property_id.in_(property_ids),
                Meter.is_active.is_(True),
                Meter.reading_due_date.is_not(None),
                Meter.reading_due_date <= due_horizon,
            )
        )
    ).all()
    for m in meter_rows:
        due = m.reading_due_date
        assert due is not None  # narrowed by the IS NOT NULL filter
        has_reading = await session.scalar(
            select(MeterReading.id)
            .where(
                MeterReading.meter_id == m.id,
                MeterReading.read_on >= quarter_start(due),
            )
            .limit(1)
        )
        if has_reading is not None:
            continue
        label = m.description or m.meter_number
        # Sort by the due date (overdue / soonest first). Berlin noon for a
        # stable cross-type ordering.
        ts = datetime.combine(due, datetime.min.time(), tzinfo=_BERLIN).astimezone(UTC)
        items.append(
            ActivityItem(
                type=ActivityType.METER_DUE,
                id=str(m.id),
                title=f"Zählerstand: {label}",
                subtitle=f"bis {_fmt_date(due)}",
                timestamp=ts,
                priority=_PRIORITY[ActivityType.METER_DUE],
                property_id=m.property_id,
                property_name=names.get(m.property_id),
                deep_link=f"whv://meter/{m.id}",
            )
        )

    # --- Rank + truncate -------------------------------------------------
    # Primary key: priority (lower first). Secondary: the recency/urgency
    # timestamp. Deadline-driven types (RESOLUTION, METER_DUE, ETV,
    # CALENDAR) carry an *event* time → soonest first (ascending). "New"
    # types (DOCUMENT, INVOICE, ANNOUNCEMENT, ETV_COMMENT) carry a
    # *created* time → newest first (descending). We bucket accordingly.
    _ascending = {
        ActivityType.RESOLUTION,
        ActivityType.METER_DUE,
        ActivityType.ETV,
        ActivityType.CALENDAR,
    }

    def _sort_key(it: ActivityItem) -> tuple[int, float]:
        epoch = it.timestamp.timestamp()
        # For ascending buckets, smaller timestamp should sort first; for
        # descending buckets, larger timestamp first → negate.
        return (it.priority, epoch if it.type in _ascending else -epoch)

    items.sort(key=_sort_key)
    return items[:limit]
