"""Liegenschafts-Kalender schemas (ADR-0018). Stored events (CRUD) + a
merged read view that folds in ETV dates derived from etv_assemblies."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import CalendarEventType


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
