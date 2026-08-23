"""Liegenschafts-Kalender schemas (ADR-0018). Stored events (CRUD) + a
merged read view that folds in ETV dates derived from etv_assemblies."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import CalendarEventType
from app.schemas.types import DecimalAsFloat


class CalendarEventCreate(BaseModel):
    event_type: CalendarEventType
    title: str | None = Field(None, max_length=200)
    starts_on: date
    ends_on: date | None = None
    assigned_user_id: uuid.UUID | None = None
    assigned_label: str | None = Field(None, max_length=200)
    note: str | None = Field(None, max_length=1000)


class CalendarEventUpdate(BaseModel):
    """PATCH — only fields present in the body are applied
    (`model_dump(exclude_unset=True)`), so explicit null clears a value."""

    event_type: CalendarEventType | None = None
    title: str | None = Field(None, max_length=200)
    starts_on: date | None = None
    ends_on: date | None = None
    assigned_user_id: uuid.UUID | None = None
    assigned_label: str | None = Field(None, max_length=200)
    note: str | None = Field(None, max_length=1000)


class CalendarEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    property_id: uuid.UUID
    event_type: CalendarEventType
    title: str | None
    starts_on: date
    ends_on: date | None
    assigned_user_id: uuid.UUID | None
    assigned_label: str | None
    note: str | None
    created_at: datetime
    updated_at: datetime


class CalendarEntry(BaseModel):
    """One entry in the merged calendar view — either a stored event or an
    ETV date derived live from the assembly record."""

    # "ETV" | "WINTERDIENST" | "KEHRWOCHE" | "TERMIN"
    kind: str
    # "event" (editable) | "etv" (read-only, mirrors the assembly)
    source: str
    id: uuid.UUID
    title: str
    starts_on: date
    ends_on: date | None = None
    assigned_user_id: uuid.UUID | None = None
    assigned_label: str | None = None
    note: str | None = None
    # Present for ETV entries so the client can deep-link to the assembly.
    assembly_id: uuid.UUID | None = None


class AgendaItem(BaseModel):
    """One upcoming appointment of the Verwalter — an ETV or a Termin —
    across every property of the org, with enough property context to drive
    there: CarPlay "Heute" and the object page's "Termine" feed on this.
    Kehrwoche/Winterdienst are owner duties and deliberately absent."""

    # "ETV" | "TERMIN"
    kind: str
    # "etv" (assembly, timed) | "event" (stored calendar event, all-day)
    source: str
    id: uuid.UUID
    title: str
    # tz-aware; all-day entries start at 00:00 Europe/Berlin.
    starts_at: datetime
    ends_at: datetime | None = None
    all_day: bool
    property_id: uuid.UUID
    property_name: str
    property_address: str | None = None
    lat: DecimalAsFloat | None = None
    lng: DecimalAsFloat | None = None
    # ETV venue ("Vor Ort", "Gemeinderaum …") — the address is the property's.
    location: str | None = None
    note: str | None = None
    assigned_label: str | None = None
    assembly_id: uuid.UUID | None = None
