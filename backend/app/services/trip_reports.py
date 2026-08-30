"""Fahrtenbuch reports (ADR-0020): the Sunday review push to each driver and
the monthly Kilometergeld statement e-mailed to the office.

Pure builders + two async runners; the Celery tasks in workers/tasks.py only
wire sessions and clients. Everything here is deterministic German text.
"""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.integrations.email.client import EmailClient, EmailError
from app.models import Property, PropertyType, Trip, TripPurpose, TripStatus, User, UserRole
from app.services import push as push_svc
from app.services.trip_statement import StatementRow, de_km, render_statement, statement_filename

_BERLIN = ZoneInfo("Europe/Berlin")


@dataclass(frozen=True)
class WeekReview:
    user_id: uuid.UUID
    trips: int
    distance_m: int
    properties: int
    open_trips: int
    # (property name, count) of ETV trips to a WEG — the ones the contract
    # lets WHV bill when the meeting was outside Kreis Stuttgart.
    billable_hints: list[tuple[str, int]]

    @property
    def body(self) -> str:
        parts = [f"Diese Woche {de_km(self.distance_m)}", f"{self.properties} Objekte"]
        if self.open_trips:
            parts.append(
                f"{self.open_trips} Fahrt unbestätigt"
                if self.open_trips == 1
                else f"{self.open_trips} Fahrten unbestätigt"
            )
        if self.billable_hints:
            names = ", ".join(n for n, _ in self.billable_hints[:2])
            more = f" +{len(self.billable_hints) - 2}" if len(self.billable_hints) > 2 else ""
            parts.append(
                f"{len(self.billable_hints)} Rechnung möglich ({names}{more}, ETV außerhalb)"
                if len(self.billable_hints) == 1
                else f"{len(self.billable_hints)} Rechnungen möglich ({names}{more}, ETV außerhalb)"
            )
        return ", ".join(parts) + "."


def week_bounds(today: date | None = None) -> tuple[datetime, datetime]:
    """Monday 00:00 → next Monday 00:00 (Europe/Berlin) of the week
    containing `today` (default: today)."""
    d = today or datetime.now(_BERLIN).date()
    monday = d - timedelta(days=d.weekday())
    start = datetime.combine(monday, datetime.min.time(), tzinfo=_BERLIN)
    return start, start + timedelta(days=7)


async def build_week_reviews(
    session: AsyncSession, *, org_id: uuid.UUID, start: datetime, end: datetime
) -> list[WeekReview]:
    trips = list(
        (
            await session.scalars(
                select(Trip).where(
                    Trip.organization_id == org_id,
                    Trip.started_at >= start,
                    Trip.started_at < end,
                )
            )
        ).all()
    )
    if not trips:
        return []
    prop_ids = {t.property_id for t in trips if t.property_id}
    props: dict[uuid.UUID, Property] = {}
    if prop_ids:
        rows = (await session.scalars(select(Property).where(Property.id.in_(prop_ids)))).all()
        props = {p.id: p for p in rows}
    out: list[WeekReview] = []
    for user_id in sorted({t.user_id for t in trips}, key=str):
        mine = [t for t in trips if t.user_id == user_id]
        hints: dict[str, int] = {}
        for t in mine:
            p = props.get(t.property_id) if t.property_id else None
            if (
                p is not None
                and p.type == PropertyType.OWNER
                and t.purpose == TripPurpose.ETV.value
                and t.invoice_id is None
            ):
                hints[p.name.split(",")[0]] = hints.get(p.name.split(",")[0], 0) + 1
        out.append(
            WeekReview(
                user_id=user_id,
                trips=len(mine),
                distance_m=sum(t.distance_m or 0 for t in mine),
                properties=len({t.property_id for t in mine if t.property_id}),
                open_trips=sum(1 for t in mine if t.status == TripStatus.OPEN.value),
                billable_hints=sorted(hints.items(), key=lambda kv: -kv[1]),
            )
        )
    return out


async def send_week_reviews(session: AsyncSession, *, org_id: uuid.UUID) -> int:
    """Sunday push to every driver with trips this week. Returns #pushes."""
    start, end = week_bounds()
    reviews = await build_week_reviews(session, org_id=org_id, start=start, end=end)
    sent = 0
    for r in reviews:
        await push_svc.notify_users(
            session,
            user_ids=[r.user_id],
            title="Fahrtenbuch — Wochenrückblick",
            body=r.body,
            deep_link="whv://tab/start",
            thread_id="fahrtenbuch-week",
        )
        sent += 1
    return sent


async def send_monthly_statements(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    settings: Settings,
    email_client: EmailClient,
    month: str | None = None,
) -> int:
    """E-mail last month's Kilometergeld statement (one PDF per driver) to
    the office address. Returns #statements sent."""
    if month is None:
        first_this_month = datetime.now(_BERLIN).date().replace(day=1)
        last_month_end = first_this_month - timedelta(days=1)
        month = last_month_end.strftime("%Y-%m")
    year, mon = (int(p) for p in month.split("-", 1))
    start = datetime(year, mon, 1, tzinfo=UTC)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)

    trips = list(
        (
            await session.scalars(
                select(Trip)
                .where(
                    Trip.organization_id == org_id,
                    Trip.started_at >= start,
                    Trip.started_at < end,
                )
                .order_by(Trip.started_at.asc())
            )
        ).all()
    )
    if not trips:
        return 0
    prop_ids = {t.property_id for t in trips if t.property_id}
    names: dict[uuid.UUID, str] = {}
    if prop_ids:
        rows = (await session.scalars(select(Property).where(Property.id.in_(prop_ids)))).all()
        names = {p.id: p.name for p in rows}
    drivers = (
        await session.scalars(
            select(User).where(
                User.id.in_({t.user_id for t in trips}), User.role == UserRole.VERWALTER
            )
        )
    ).all()

    attachments: list[dict[str, str]] = []
    summary_lines: list[str] = []
    for driver in drivers:
        mine = [t for t in trips if t.user_id == driver.id]
        rows_ = [
            StatementRow(trip=t, property_name=names.get(t.property_id) if t.property_id else None)
            for t in mine
        ]
        pdf = render_statement(
            rows=rows_,
            month=month,
            driver_label=driver.email,
            rate_cents_per_km=settings.trip_rate_cents_per_km,
            payee_label=f"{settings.trip_payee_name}, {settings.trip_payee_address}",
        )
        attachments.append(
            {
                "filename": statement_filename(month, driver.email),
                "content": base64.b64encode(pdf).decode("ascii"),
            }
        )
        total_m = sum(t.distance_m or 0 for t in mine)
        total_cents = sum(t.amount_cents for t in mine)
        summary_lines.append(
            f"{driver.email}: {len(mine)} Fahrten, {de_km(total_m)}, "
            f"{total_cents / 100:.2f} EUR Kilometergeld".replace(".", ",")
        )

    if not attachments:
        return 0
    text = (
        f"Kilometergeld-Abrechnung {month}\n\n"
        + "\n".join(summary_lines)
        + f"\n\nZahlungsempfänger: {settings.trip_payee_name}, {settings.trip_payee_address}\n"
        "Die Abrechnungen je Fahrer liegen als PDF bei. Erstellt automatisch am "
        f"{datetime.now(_BERLIN).strftime('%d.%m.%Y %H:%M')} vom WHV-Fahrtenbuch."
    )
    try:
        await email_client.send(
            to=settings.trip_report_email,
            subject=f"Fahrtenbuch: Kilometergeld-Abrechnung {month}",
            html="<p>" + text.replace("\n", "<br>") + "</p>",
            text=text,
            attachments=attachments,
        )
    except EmailError:
        raise
    return len(attachments)
