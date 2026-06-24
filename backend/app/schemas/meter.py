"""Zähler (meter) + Zählerstand (reading) request/response schemas."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import MeterReadingSource, MeterType


class MeterCreate(BaseModel):
    meter_number: str = Field(..., min_length=1, max_length=120)
    meter_type: MeterType
    # Optional unit link — set for Wohnungs-meters, NULL for common /
    # property-wide meters (Allgemeinstrom, Betriebsstrom, main meter).
    unit_id: uuid.UUID | None = None
    description: str | None = Field(None, max_length=200)
    location: str | None = Field(None, max_length=200)
    # Measurement unit ("kWh", "m³"). Defaulted from meter_type when blank.
    unit_label: str | None = Field(None, max_length=20)
    installation_date: date | None = None
    calibration_valid_until: date | None = None
    supplier_name: str | None = Field(None, max_length=120)
    supplier_email: EmailStr | None = None


class MeterUpdate(BaseModel):
    """PATCH semantics — only fields present in the request body are
    applied (the handler uses `model_dump(exclude_unset=True)`), so an
    explicit `null` clears a value while an omitted field is left as-is."""

    meter_number: str | None = Field(None, min_length=1, max_length=120)
    meter_type: MeterType | None = None
    unit_id: uuid.UUID | None = None
    description: str | None = Field(None, max_length=200)
    location: str | None = Field(None, max_length=200)
    unit_label: str | None = Field(None, max_length=20)
    installation_date: date | None = None
    calibration_valid_until: date | None = None
    supplier_name: str | None = Field(None, max_length=120)
    supplier_email: EmailStr | None = None
    is_active: bool | None = None


class MeterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    property_id: uuid.UUID
    unit_id: uuid.UUID | None
    meter_number: str
    meter_type: MeterType
    description: str | None
    location: str | None
    unit_label: str | None
    installation_date: date | None
    calibration_valid_until: date | None
    supplier_name: str | None
    supplier_email: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    # Denormalised for list views — populated by the service, defaulted so
    # `model_validate(meter_row)` works before enrichment.
    unit_name: str | None = None
    latest_reading_value: Decimal | None = None
    latest_reading_on: date | None = None
    reading_count: int = 0


class MeterBulkCreateRequest(BaseModel):
    """Seed many meters at once (the Verwalter pastes an extracted list)."""

    meters: list[MeterCreate] = Field(..., min_length=1, max_length=500)


class MeterBulkCreateError(BaseModel):
    index: int
    meter_number: str | None = None
    error: str


class MeterBulkCreateResponse(BaseModel):
    created: list[MeterResponse]
    errors: list[MeterBulkCreateError]


class MeterReadingResponse(BaseModel):
    id: uuid.UUID
    meter_id: uuid.UUID
    value: Decimal
    read_on: date
    source: MeterReadingSource
    note: str | None = None
    has_photo: bool = False
    photo_mime_type: str | None = None
    reported_by_user_id: uuid.UUID | None = None
    reported_by_email: str | None = None
    created_at: datetime


class MeterReadingOCR(BaseModel):
    """Structured output requested from the LLM for a meter-face photo.

    Permissive (string reading) so the model isn't forced to guess a
    number — the handler coerces to Decimal and the user confirms.
    """

    reading: str | None = Field(
        None,
        description=(
            "The current meter reading shown on the counter/display as digits, "
            "including the decimal part if the meter shows decimal (red) digits. "
            "Null if not clearly legible — do not guess."
        ),
    )
    meter_number: str | None = Field(
        None,
        description="The Zaehlernummer (serial) printed on the meter, if clearly visible.",
    )
    confidence: float | None = Field(
        None,
        description="Confidence from 0.0 to 1.0 that the reading digits were identified correctly.",
    )


class MeterReadingOCRResult(BaseModel):
    """API response for the OCR-preview endpoint — a suggestion the user
    confirms or overrides before submitting the actual reading."""

    suggested_value: Decimal | None = None
    meter_number: str | None = None
    confidence: float | None = None
    ocr_raw: str | None = None
    # False when the LLM provider isn't configured — the client then just
    # shows manual entry without an error (OCR is a convenience, not a gate).
    provider_available: bool = True
