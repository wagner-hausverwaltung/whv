"""Zähler (meter) + Zählerstand (reading) request/response schemas."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer

from app.models import MeterReadingSource, MeterType


def _decimal_to_float(v: Decimal | None) -> float | None:
    """Serialize Decimal reading/value fields as JSON numbers. Pydantic v2's
    default is a JSON string, which the iOS clients (Double) can't decode —
    so the meter list 'Couldn't load' once any reading existed."""
    return float(v) if v is not None else None


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
    reading_due_date: date | None = None
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
    reading_due_date: date | None = None
    supplier_name: str | None = Field(None, max_length=120)
    supplier_email: EmailStr | None = None
    is_active: bool | None = None


class MeterReplaceRequest(BaseModel):
    """Zählerwechsel — swap a meter. The OLD meter gets `old_final_reading`
    (Schlussstand) + goes inactive; a NEW meter with `new_meter_number` is
    created active with `new_initial_reading` (Anfangsstand)."""

    change_date: date
    new_meter_number: str = Field(..., min_length=1, max_length=120)
    old_final_reading: Decimal = Field(..., ge=0)
    new_initial_reading: Decimal = Field(..., ge=0)


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
    reading_due_date: date | None
    supplier_name: str | None
    supplier_email: str | None
    is_active: bool
    # Zählerwechsel — set on the OLD meter once it's swapped out: when it
    # happened + the link to the replacement meter.
    replaced_at: date | None
    successor_meter_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    # Denormalised for list views — populated by the service, defaulted so
    # `model_validate(meter_row)` works before enrichment.
    unit_name: str | None = None
    latest_reading_value: Decimal | None = None
    latest_reading_on: date | None = None
    reading_count: int = 0

    @field_serializer("latest_reading_value")
    def _ser_latest_reading_value(self, v: Decimal | None) -> float | None:
        return _decimal_to_float(v)


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

    @field_serializer("value")
    def _ser_value(self, v: Decimal) -> float:
        return float(v)


class MeterReadingUpdate(BaseModel):
    """Admin correction of a recorded reading — PATCH semantics: only fields
    present in the body are applied (`model_dump(exclude_unset=True)`), so an
    omitted field is left as-is. Used to fix a misread (e.g. a missed decimal:
    295900 → 2959,00). Admin edits do not run the plausibility check."""

    value: Decimal | None = Field(None, ge=0)
    read_on: date | None = None
    note: str | None = Field(None, max_length=2000)


class ReadingWarning(BaseModel):
    """A plausibility concern raised when a new reading is submitted. Surfaced
    to the client as the `detail` of a 409 (soft block) so the user can confirm
    and resubmit with `force=true`. `last_value`/`new_value` are JSON numbers
    so the iOS client (Double) decodes them directly."""

    # "below_last" | "unusual_high" | "unusual_low"
    code: str
    message: str
    last_value: Decimal | None = None
    new_value: Decimal

    @field_serializer("last_value")
    def _ser_last_value(self, v: Decimal | None) -> float | None:
        return _decimal_to_float(v)

    @field_serializer("new_value")
    def _ser_new_value(self, v: Decimal) -> float:
        return float(v)


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

    @field_serializer("suggested_value")
    def _ser_suggested_value(self, v: Decimal | None) -> float | None:
        return _decimal_to_float(v)
