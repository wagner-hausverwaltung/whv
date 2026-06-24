"""Liegenschafts-Kalender endpoints (ADR-0018).

Member (read-only):
  GET /me/properties/{id}/calendar?year=&month=     merged month view

Admin (Verwalter):
  GET    /admin/properties/{id}/calendar?year=&month=    merged month view
  POST   /admin/properties/{id}/calendar/events          create event
  PATCH  /admin/calendar/events/{id}                      edit event
  DELETE /admin/calendar/events/{id}                      delete event
  GET    /admin/properties/{id}/calendar.pdf?year=&month= WHV-design month PDF
"""

import asyncio
import calendar as _calmod
import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.me import _visible_properties_stmt
from app.auth.dependencies import get_current_user, require_role
from app.db import get_session
from app.integrations.pdf.calendar_document import render_calendar_pdf
from app.models import CalendarEvent, Property, User, UserRole
from app.schemas.calendar import (
    CalendarEntry,
    CalendarEventCreate,
    CalendarEventResponse,
    CalendarEventUpdate,
)
from app.services import calendar as calendar_svc

me_router = APIRouter(prefix="/me", tags=["calendar"])
admin_router = APIRouter(prefix="/admin", tags=["calendar"])

_verwalter_only = require_role(UserRole.VERWALTER)


def _month_range(year: int | None, month: int | None) -> tuple[date, date, int, int]:
    today = date.today()
    y = year or today.year
    m = month or today.month
    if not (1 <= m <= 12):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ungültiger Monat.")
    last = _calmod.monthrange(y, m)[1]
    return date(y, m, 1), date(y, m, last), y, m


def _format_address(p: Property) -> str | None:
    street = " ".join(part for part in (p.street, p.number) if part).strip()
    zip_city = " ".join(part for part in (p.postal_code, p.city) if part).strip()
    combined = " · ".join(part for part in (street, zip_city) if part)
    return combined or None


async def _member_property_or_404(
    session: AsyncSession, user: User, property_id: uuid.UUID
) -> Property:
    prop: Property | None = await session.scalar(
        _visible_properties_stmt(user).where(Property.id == property_id)
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liegenschaft not found")
    return prop


async def _admin_property_or_404(
    session: AsyncSession, user: User, property_id: uuid.UUID
) -> Property:
    prop = await session.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.organization_id == user.organization_id,
            Property.deleted_at.is_(None),
        )
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liegenschaft not found")
    return prop


async def _admin_event_or_404(
    session: AsyncSession, user: User, event_id: uuid.UUID
) -> CalendarEvent:
    event = await calendar_svc.get_event(
        session, event_id=event_id, organization_id=user.organization_id
    )
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Termin not found")
    return event


# --- member ------------------------------------------------------------------


@me_router.get("/properties/{property_id}/calendar", response_model=list[CalendarEntry])
async def my_calendar(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    year: int | None = None,
    month: int | None = None,
) -> list[CalendarEntry]:
    await _member_property_or_404(session, current_user, property_id)
    start, end, _, _ = _month_range(year, month)
    return await calendar_svc.merged_entries(
        session,
        organization_id=current_user.organization_id,
        property_id=property_id,
        range_start=start,
        range_end=end,
    )


# --- admin -------------------------------------------------------------------


@admin_router.get("/properties/{property_id}/calendar", response_model=list[CalendarEntry])
async def admin_calendar(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    year: int | None = None,
    month: int | None = None,
) -> list[CalendarEntry]:
    await _admin_property_or_404(session, current_user, property_id)
    start, end, _, _ = _month_range(year, month)
    return await calendar_svc.merged_entries(
        session,
        organization_id=current_user.organization_id,
        property_id=property_id,
        range_start=start,
        range_end=end,
    )


@admin_router.post(
    "/properties/{property_id}/calendar/events",
    response_model=CalendarEventResponse,
    status_code=status.HTTP_201_CREATED,
)
async def admin_create_event(
    property_id: uuid.UUID,
    req: CalendarEventCreate,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CalendarEventResponse:
    await _admin_property_or_404(session, current_user, property_id)
    try:
        event = await calendar_svc.create_event(
            session,
            organization_id=current_user.organization_id,
            property_id=property_id,
            actor_id=current_user.id,
            data=req,
        )
    except calendar_svc.CalendarServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return CalendarEventResponse.model_validate(event)


@admin_router.patch("/calendar/events/{event_id}", response_model=CalendarEventResponse)
async def admin_update_event(
    event_id: uuid.UUID,
    req: CalendarEventUpdate,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CalendarEventResponse:
    event = await _admin_event_or_404(session, current_user, event_id)
    try:
        event = await calendar_svc.update_event(
            session, event=event, actor_id=current_user.id, data=req
        )
    except calendar_svc.CalendarServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return CalendarEventResponse.model_validate(event)


@admin_router.delete("/calendar/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_event(
    event_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    event = await _admin_event_or_404(session, current_user, event_id)
    await calendar_svc.delete_event(session, event=event, actor_id=current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("/properties/{property_id}/calendar.pdf")
async def admin_calendar_pdf(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    year: int | None = None,
    month: int | None = None,
) -> Response:
    prop = await _admin_property_or_404(session, current_user, property_id)
    start, end, y, m = _month_range(year, month)
    entries = await calendar_svc.merged_entries(
        session,
        organization_id=current_user.organization_id,
        property_id=property_id,
        range_start=start,
        range_end=end,
    )
    pdf = await asyncio.to_thread(
        render_calendar_pdf,
        year=y,
        month=m,
        property_name=prop.name,
        property_address=_format_address(prop),
        entries=calendar_svc.to_pdf_entries(entries),
        generated_at=datetime.now(UTC),
    )
    filename = f"kalender-{y}-{m:02d}-{property_id.hex[:8]}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
