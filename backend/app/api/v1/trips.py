"""Fahrtenbuch endpoints (ADR-0020).

`/me/trips` — the driver's own log (Verwalter role only; owners never track).
`/admin/trips` — every Verwalter's trips for the org, with totals and the
Auslagen split per property, plus a CSV export for the Kilometergeld statement.

Both are Verwalter-gated: Kilometergeld is an internal matter between WHV and
its property managers, and the per-property Auslagen go to the WEG via the
regular Jahresabrechnung, not through this API.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.config import Settings, get_settings
from app.db import get_session
from app.integrations.email.client import EmailClient, EmailError, get_email_client
from app.models import (
    AuditLog,
    Contact,
    OfferInquiry,
    Property,
    Trip,
    TripPurpose,
    TripStatus,
    User,
    UserRole,
)
from app.schemas.trip import (
    AdminTripListResponse,
    DelayNoticeRequest,
    DelayNoticeResponse,
    TripCompleteRequest,
    TripPropertyTotal,
    TripResponse,
    TripStartRequest,
    TripSummary,
    TripUpdateRequest,
)
from app.services.units import _contact_label

me_router = APIRouter(prefix="/me/trips", tags=["trips"])
admin_router = APIRouter(prefix="/admin/trips", tags=["admin-trips"])

_verwalter_only = require_role(UserRole.VERWALTER)


# --- helpers ------------------------------------------------------------------


async def _to_response(session: AsyncSession, trips: list[Trip]) -> list[TripResponse]:
    """Resolve user e-mails, property names and inquiry addresses in three
    round-trips, not 3N."""
    user_ids = {t.user_id for t in trips}
    prop_ids = {t.property_id for t in trips if t.property_id is not None}
    inquiry_ids = {t.inquiry_id for t in trips if t.inquiry_id is not None}
    emails: dict[uuid.UUID, str] = {}
    names: dict[uuid.UUID, str] = {}
    addresses: dict[uuid.UUID, str | None] = {}
    if user_ids:
        user_rows = (await session.scalars(select(User).where(User.id.in_(user_ids)))).all()
        emails = {u.id: u.email for u in user_rows}
    if prop_ids:
        prop_rows = (await session.scalars(select(Property).where(Property.id.in_(prop_ids)))).all()
        names = {p.id: p.name for p in prop_rows}
    if inquiry_ids:
        inq_rows = (
            await session.scalars(select(OfferInquiry).where(OfferInquiry.id.in_(inquiry_ids)))
        ).all()
        addresses = {i.id: i.object_address for i in inq_rows}
    out: list[TripResponse] = []
    for t in trips:
        resp = TripResponse.model_validate(t)
        resp.user_email = emails.get(t.user_id)
        resp.property_name = names.get(t.property_id) if t.property_id else None
        resp.inquiry_address = addresses.get(t.inquiry_id) if t.inquiry_id else None
        out.append(resp)
    return out


def _object_label(t: TripResponse) -> str | None:
    """What the "Objekt" column shows: the property, else the prospect's
    address from the linked inquiry (a Besichtigung before the WEG exists)."""
    if t.property_name:
        return t.property_name
    if t.inquiry_id is not None:
        return f"Anfrage: {t.inquiry_address or '(ohne Adresse)'}"
    return None


async def _own_trip(session: AsyncSession, user: User, trip_id: uuid.UUID) -> Trip:
    trip = await session.scalar(
        select(Trip).where(
            Trip.id == trip_id,
            Trip.organization_id == user.organization_id,
            Trip.user_id == user.id,
        )
    )
    if trip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fahrt nicht gefunden")
    return trip


async def _org_property(session: AsyncSession, user: User, property_id: uuid.UUID) -> Property:
    prop = await session.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.organization_id == user.organization_id,
            Property.deleted_at.is_(None),
        )
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Objekt nicht gefunden")
    return prop


async def _org_inquiry(session: AsyncSession, user: User, inquiry_id: uuid.UUID) -> OfferInquiry:
    inquiry = await session.scalar(
        select(OfferInquiry).where(
            OfferInquiry.id == inquiry_id,
            OfferInquiry.organization_id == user.organization_id,
        )
    )
    if inquiry is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Anfrage nicht gefunden"
        )
    return inquiry


def _reindex_inquiry_card(
    settings: Settings, org_id: uuid.UUID, *inquiry_ids: uuid.UUID | None
) -> None:
    """The inquiry's RAG card carries "Besichtigt: …" — refresh it whenever a
    linked trip appears, moves or goes. No-op where RAG is off (everything
    but prod) and for trips without an inquiry."""
    ids = {i for i in inquiry_ids if i is not None}
    if not ids or not settings.rag_enabled:
        return
    from app.workers.tasks import index_rag_masterdata

    for inquiry_id in ids:
        index_rag_masterdata.delay(str(org_id), str(inquiry_id), "anfrage")


def _apply_update(trip: Trip, req: TripUpdateRequest) -> None:
    fields = req.model_fields_set
    if "ended_at" in fields and req.ended_at is not None:
        if req.ended_at <= trip.started_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Ende liegt vor dem Start"
            )
        trip.ended_at = req.ended_at
    for name in ("end_lat", "end_lng", "distance_m", "route_polyline", "note"):
        if name in fields:
            setattr(trip, name, getattr(req, name))
    if "property_id" in fields:
        trip.property_id = req.property_id
    if "inquiry_id" in fields:
        trip.inquiry_id = req.inquiry_id
    if "purpose" in fields and req.purpose is not None:
        trip.purpose = req.purpose
    # Status follows the data: ended → OPEN, ended + purpose → CONFIRMED.
    if trip.ended_at is not None:
        trip.status = TripStatus.CONFIRMED.value if trip.purpose else TripStatus.OPEN.value


def _month_bounds(month: str | None) -> tuple[datetime, datetime] | None:
    """'YYYY-MM' → [first day, first day of next month) in UTC."""
    if not month:
        return None
    try:
        year, mon = (int(p) for p in month.split("-", 1))
        start = datetime(year, mon, 1, tzinfo=UTC)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="month muss YYYY-MM sein"
        ) from None
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, end


# --- /me/trips ----------------------------------------------------------------


@me_router.get("", response_model=list[TripResponse])
async def list_my_trips(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    month: Annotated[str | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[TripResponse]:
    stmt = select(Trip).where(
        Trip.organization_id == current_user.organization_id, Trip.user_id == current_user.id
    )
    if (bounds := _month_bounds(month)) is not None:
        stmt = stmt.where(Trip.started_at >= bounds[0], Trip.started_at < bounds[1])
    if status_filter:
        stmt = stmt.where(Trip.status == status_filter)
    stmt = stmt.order_by(Trip.started_at.desc()).limit(limit)
    return await _to_response(session, list((await session.scalars(stmt)).all()))


@me_router.get("/running", response_model=TripResponse | None)
async def my_running_trip(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TripResponse | None:
    """The trip currently being tracked, if any — lets the app resume after a
    relaunch instead of opening a second one."""
    trip = await session.scalar(
        select(Trip).where(Trip.user_id == current_user.id, Trip.status == TripStatus.RUNNING.value)
    )
    if trip is None:
        return None
    return (await _to_response(session, [trip]))[0]


@me_router.post("", response_model=TripResponse, status_code=status.HTTP_201_CREATED)
async def start_trip(
    req: TripStartRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TripResponse:
    """Open a RUNNING trip. Idempotent: a second start while one is running
    returns the running one — a flaky upload must not fork the log."""
    running = await session.scalar(
        select(Trip).where(Trip.user_id == current_user.id, Trip.status == TripStatus.RUNNING.value)
    )
    if running is not None:
        return (await _to_response(session, [running]))[0]
    if req.inquiry_id is not None:
        await _org_inquiry(session, current_user, req.inquiry_id)
    trip = Trip(
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        status=TripStatus.RUNNING.value,
        source=req.source,
        started_at=req.started_at or datetime.now(UTC),
        start_lat=req.start_lat,
        start_lng=req.start_lng,
        inquiry_id=req.inquiry_id,
        rate_cents_per_km=settings.trip_rate_cents_per_km,
    )
    session.add(trip)
    await session.commit()
    await session.refresh(trip)
    _reindex_inquiry_card(settings, current_user.organization_id, trip.inquiry_id)
    return (await _to_response(session, [trip]))[0]


@me_router.post("/complete", response_model=TripResponse, status_code=status.HTTP_201_CREATED)
async def upload_complete_trip(
    req: TripCompleteRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TripResponse:
    """Store a finished trip in one go (automatic detection uploads here)."""
    if req.property_id is not None:
        await _org_property(session, current_user, req.property_id)
    if req.inquiry_id is not None:
        await _org_inquiry(session, current_user, req.inquiry_id)
    trip = Trip(
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        status=TripStatus.CONFIRMED.value if req.purpose else TripStatus.OPEN.value,
        source=req.source,
        purpose=req.purpose,
        property_id=req.property_id,
        inquiry_id=req.inquiry_id,
        started_at=req.started_at,
        ended_at=req.ended_at,
        start_lat=req.start_lat,
        start_lng=req.start_lng,
        end_lat=req.end_lat,
        end_lng=req.end_lng,
        distance_m=req.distance_m,
        route_polyline=req.route_polyline,
        note=req.note,
        rate_cents_per_km=settings.trip_rate_cents_per_km,
    )
    session.add(trip)
    await session.commit()
    await session.refresh(trip)
    _reindex_inquiry_card(settings, current_user.organization_id, trip.inquiry_id)
    return (await _to_response(session, [trip]))[0]


@me_router.patch("/{trip_id}", response_model=TripResponse)
async def update_my_trip(
    trip_id: uuid.UUID,
    req: TripUpdateRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TripResponse:
    trip = await _own_trip(session, current_user, trip_id)
    if req.property_id is not None:
        await _org_property(session, current_user, req.property_id)
    if req.inquiry_id is not None:
        await _org_inquiry(session, current_user, req.inquiry_id)
    inquiry_before = trip.inquiry_id
    _apply_update(trip, req)
    await session.commit()
    await session.refresh(trip)
    _reindex_inquiry_card(settings, current_user.organization_id, inquiry_before, trip.inquiry_id)
    return (await _to_response(session, [trip]))[0]


@me_router.delete("/{trip_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_trip(
    trip_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Drop a mis-detected trip (passenger ride, test drive). Audited, because
    the log is the basis of a reimbursement."""
    trip = await _own_trip(session, current_user, trip_id)
    inquiry_id = trip.inquiry_id
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="trip_deleted",
            target_type="trips",
            target_id=str(trip.id),
            payload_json={
                "started_at": trip.started_at.isoformat(),
                "distance_m": trip.distance_m,
                "purpose": trip.purpose,
            },
        )
    )
    await session.delete(trip)
    await session.commit()
    _reindex_inquiry_card(settings, current_user.organization_id, inquiry_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@me_router.post("/delay-notice", response_model=DelayNoticeResponse)
async def send_delay_notice(
    req: DelayNoticeRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DelayNoticeResponse:
    """One-tap "Ich verspäte mich" from CarPlay: e-mails the contact on the
    Verwalter's behalf. Messaging from a Driving-Task app isn't allowed, so
    the mail goes out server-side; reply-to is the Verwalter."""
    contact = await session.scalar(
        select(Contact).where(
            Contact.id == req.contact_id,
            Contact.organization_id == current_user.organization_id,
            Contact.deleted_at.is_(None),
        )
    )
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kontakt nicht gefunden")
    if not contact.email:
        return DelayNoticeResponse(sent=False, to=None, detail="Kontakt hat keine E-Mail-Adresse.")

    prop_name = None
    if req.property_id is not None:
        prop = await session.get(Property, req.property_id)
        prop_name = (
            prop.name if prop and prop.organization_id == current_user.organization_id else None
        )

    sender = current_user.email.split("@", 1)[0].replace(".", " ").title()
    where = f" ({prop_name})" if prop_name else ""
    maps = (
        f"https://maps.apple.com/?ll={req.lat},{req.lng}&q=Standort"
        if req.lat is not None and req.lng is not None
        else None
    )
    subject = f"Wagner Hausverwaltung: {sender} verspätet sich um ca. {req.minutes} Minuten"
    text = (
        f"Guten Tag {_contact_label(contact)},\n\n"
        f"{sender} von der Wagner Hausverwaltung verspätet sich zum Termin{where} um "
        f"etwa {req.minutes} Minuten. Wir bitten um Entschuldigung.\n"
        + (f"\nAktueller Standort: {maps}\n" if maps else "")
        + "\nBei Rückfragen antworten Sie einfach auf diese E-Mail.\n\nWagner Hausverwaltung GmbH"
    )
    html = text.replace("\n", "<br>")
    if maps:
        html = html.replace(maps, f'<a href="{maps}">{maps}</a>')
    try:
        await email_client.send(
            to=contact.email,
            subject=subject,
            html=f"<p>{html}</p>",
            text=text,
            reply_to=current_user.email,
        )
    except EmailError as exc:
        return DelayNoticeResponse(
            sent=False, to=contact.email, detail=f"Versand fehlgeschlagen: {exc}"
        )
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="delay_notice_sent",
            target_type="contacts",
            target_id=str(contact.id),
            payload_json={
                "minutes": req.minutes,
                "property_id": str(req.property_id) if req.property_id else None,
            },
        )
    )
    await session.commit()
    return DelayNoticeResponse(
        sent=True, to=contact.email, detail=f"Mitteilung an {contact.email} gesendet."
    )


# --- /admin/trips -------------------------------------------------------------


def _admin_filters(
    stmt: Select[tuple[Trip]],
    *,
    org_id: uuid.UUID,
    month: str | None,
    user_id: uuid.UUID | None,
    property_id: uuid.UUID | None,
) -> Select[tuple[Trip]]:
    stmt = stmt.where(Trip.organization_id == org_id)
    if (bounds := _month_bounds(month)) is not None:
        stmt = stmt.where(Trip.started_at >= bounds[0], Trip.started_at < bounds[1])
    if user_id is not None:
        stmt = stmt.where(Trip.user_id == user_id)
    if property_id is not None:
        stmt = stmt.where(Trip.property_id == property_id)
    return stmt


@admin_router.get("", response_model=AdminTripListResponse)
async def admin_list_trips(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    month: Annotated[str | None, Query()] = None,
    user_id: Annotated[uuid.UUID | None, Query()] = None,
    property_id: Annotated[uuid.UUID | None, Query()] = None,
) -> AdminTripListResponse:
    stmt = _admin_filters(
        select(Trip),
        org_id=current_user.organization_id,
        month=month,
        user_id=user_id,
        property_id=property_id,
    ).order_by(Trip.started_at.desc())
    trips = list((await session.scalars(stmt)).all())
    items = await _to_response(session, trips)

    billable = [t for t in trips if t.is_billable]
    summary = TripSummary(
        trips=len(trips),
        distance_m=sum(t.distance_m or 0 for t in trips),
        amount_cents=sum(t.amount_cents for t in trips),
        billable_trips=len(billable),
        billable_distance_m=sum(t.distance_m or 0 for t in billable),
    )

    by_prop: dict[uuid.UUID | None, TripPropertyTotal] = {}
    names = {i.property_id: i.property_name for i in items if i.property_id}
    for t in billable:
        key = t.property_id
        cur = by_prop.get(key)
        if cur is None:
            cur = TripPropertyTotal(
                property_id=key,
                property_name=names.get(key) or "(ohne Objekt)" if key else "(ohne Objekt)",
                trips=0,
                distance_m=0,
                amount_cents=0,
            )
            by_prop[key] = cur
        cur.trips += 1
        cur.distance_m += t.distance_m or 0
        cur.amount_cents += t.amount_cents
    by_property = sorted(by_prop.values(), key=lambda p: -p.amount_cents)
    return AdminTripListResponse(items=items, summary=summary, by_property=by_property)


@admin_router.patch("/{trip_id}", response_model=TripResponse)
async def admin_update_trip(
    trip_id: uuid.UUID,
    req: TripUpdateRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TripResponse:
    """Correct any driver's trip (wrong property, forgotten purpose)."""
    trip = await session.scalar(
        select(Trip).where(Trip.id == trip_id, Trip.organization_id == current_user.organization_id)
    )
    if trip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fahrt nicht gefunden")
    if req.property_id is not None:
        await _org_property(session, current_user, req.property_id)
    if req.inquiry_id is not None:
        await _org_inquiry(session, current_user, req.inquiry_id)
    before = {
        "purpose": trip.purpose,
        "property_id": str(trip.property_id) if trip.property_id else None,
        "inquiry_id": str(trip.inquiry_id) if trip.inquiry_id else None,
    }
    _apply_update(trip, req)
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="trip_edited",
            target_type="trips",
            target_id=str(trip.id),
            payload_json={"before": before, "fields": sorted(req.model_fields_set)},
        )
    )
    await session.commit()
    await session.refresh(trip)
    _reindex_inquiry_card(
        settings,
        current_user.organization_id,
        uuid.UUID(before["inquiry_id"]) if before["inquiry_id"] else None,
        trip.inquiry_id,
    )
    return (await _to_response(session, [trip]))[0]


@admin_router.get("/export.csv")
async def admin_export_trips_csv(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    month: Annotated[str | None, Query()] = None,
    user_id: Annotated[uuid.UUID | None, Query()] = None,
    property_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Response:
    """Kilometergeld statement as Excel-DE friendly CSV (';' separated,
    decimal comma)."""
    stmt = _admin_filters(
        select(Trip),
        org_id=current_user.organization_id,
        month=month,
        user_id=user_id,
        property_id=property_id,
    ).order_by(Trip.started_at.asc())
    items = await _to_response(session, list((await session.scalars(stmt)).all()))

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(
        [
            "Datum",
            "Start",
            "Ende",
            "Fahrer",
            "Objekt",
            "Zweck",
            "km",
            "Satz ct/km",
            "Betrag EUR",
            "Quelle",
            "Notiz",
        ]
    )

    def de(d: Decimal | int | float, places: int = 2) -> str:
        return f"{Decimal(d):.{places}f}".replace(".", ",")

    for i in items:
        w.writerow(
            [
                i.started_at.strftime("%d.%m.%Y"),
                i.started_at.strftime("%H:%M"),
                i.ended_at.strftime("%H:%M") if i.ended_at else "",
                i.user_email or "",
                _object_label(i) or "",
                i.purpose or "",
                de(i.distance_km, 1),
                str(i.rate_cents_per_km),
                de(Decimal(i.amount_cents) / 100),
                i.source,
                (i.note or "").replace("\n", " "),
            ]
        )
    total_km = sum((i.distance_km for i in items), Decimal(0))
    total_eur = Decimal(sum(i.amount_cents for i in items)) / 100
    w.writerow([])
    w.writerow(["Summe", "", "", "", "", "", de(total_km, 1), "", de(total_eur), "", ""])

    name = f"Fahrtenbuch-{month or date.today().strftime('%Y-%m')}.csv"
    # BOM so Excel opens it as UTF-8 without an import dialog.
    return Response(
        content="﻿" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@admin_router.get("/statement.pdf")
async def admin_statement_pdf(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    month: Annotated[str, Query(description="YYYY-MM")],
    user_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Response:
    """Kilometergeld-Abrechnung for one month as PDF — one driver (user_id)
    or, when omitted, the calling Verwalter. Lists every trip, the month
    total and the Auslagen regrouped per property."""
    from app.services.trip_statement import StatementRow, render_statement, statement_filename

    if _month_bounds(month) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="month fehlt")
    driver_id = user_id or current_user.id
    driver = await session.get(User, driver_id)
    if driver is None or driver.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fahrer nicht gefunden")

    stmt = _admin_filters(
        select(Trip),
        org_id=current_user.organization_id,
        month=month,
        user_id=driver_id,
        property_id=None,
    ).order_by(Trip.started_at.asc())
    trips = list((await session.scalars(stmt)).all())
    resolved = await _to_response(session, trips)
    rows = [
        StatementRow(
            trip=t,
            property_name=r.property_name,
            inquiry_address=(
                (r.inquiry_address or "(ohne Adresse)") if r.inquiry_id is not None else None
            ),
        )
        for t, r in zip(trips, resolved, strict=True)
    ]
    pdf = render_statement(
        rows=rows,
        month=month,
        driver_label=driver.email,
        rate_cents_per_km=settings.trip_rate_cents_per_km,
    )
    name = statement_filename(month, driver.email)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# Re-exported for main.py; TripPurpose kept importable for future validators.
__all__ = ["TripPurpose", "admin_router", "me_router"]
