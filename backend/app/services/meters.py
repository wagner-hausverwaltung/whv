"""Zähler (meter) + Zählerstand (reading) service.

CRUD + bulk-create for meters, reading submission (optionally with a
photo), LLM OCR of a meter photo, and a CSV export of a property's
readings. Endpoints stay thin; org/property scoping is enforced by the
callers (they resolve the meter within the user's scope first).
"""

from __future__ import annotations

import csv
import io
import logging
import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.integrations.llm import LLMProvider, get_llm_provider
from app.integrations.llm.base import LLMProviderUnavailableError
from app.integrations.storage.meter_readings import (
    MeterPhotoStorageError,
    write_photo,
)
from app.models import (
    AuditLog,
    Meter,
    MeterReading,
    MeterReadingSource,
    MeterType,
    Unit,
    User,
)
from app.schemas.meter import (
    MeterBulkCreateError,
    MeterCreate,
    MeterReadingOCR,
    MeterReadingOCRResult,
    MeterReadingResponse,
    MeterResponse,
    MeterUpdate,
)
from app.services import llm_audit

logger = logging.getLogger(__name__)


class MeterServiceError(ValueError):
    """Validation error mapped to HTTP 400 by the endpoints."""


_DEFAULT_UNIT_LABEL: dict[MeterType, str | None] = {
    MeterType.STROM: "kWh",
    MeterType.GAS: "m³",
    MeterType.WASSER: "m³",
    MeterType.WARMWASSER: "m³",
    MeterType.WAERME: "kWh",
    MeterType.SONSTIGES: None,
}

_OCR_PROMPT = (
    "This photo shows a utility meter (Stromzähler, Gaszähler, Wasserzähler "
    "or Wärmemengenzähler). Read the current value shown on the mechanical "
    "counter or digital display. Return it as digits in the `reading` field, "
    "including the decimal part only if the meter clearly shows decimal (often "
    "red) digits. If the value is not clearly legible, return null for "
    "`reading` rather than guessing. If a Zählernummer (serial) is clearly "
    "printed on the meter, return it in `meter_number`."
)


def _unit_label(unit: Unit) -> str:
    """Human label for a unit — there's no single name column, so compose
    from the Impower human-readable id + floor/position."""
    primary = unit.unit_hr_id or " ".join(p for p in (unit.floor, unit.position) if p)
    return primary or f"Einheit {unit.id.hex[:6]}"


def _coerce_decimal(raw: str | None) -> Decimal | None:
    """Best-effort parse of an OCR'd reading into a Decimal. German meters
    print a comma decimal; we normalise and extract the first numeric token."""
    if not raw:
        return None
    cleaned = raw.strip().replace(",", ".").replace(" ", "")
    match = re.search(r"\d+(?:\.\d+)?", cleaned)
    if match is None:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def to_meter_response(
    meter: Meter,
    *,
    unit_name: str | None = None,
    latest: MeterReading | None = None,
    reading_count: int = 0,
) -> MeterResponse:
    resp = MeterResponse.model_validate(meter)
    resp.unit_name = unit_name
    resp.reading_count = reading_count
    if latest is not None:
        resp.latest_reading_value = latest.value
        resp.latest_reading_on = latest.read_on
    return resp


def to_reading_response(
    reading: MeterReading, *, reported_by_email: str | None = None
) -> MeterReadingResponse:
    return MeterReadingResponse(
        id=reading.id,
        meter_id=reading.meter_id,
        value=reading.value,
        read_on=reading.read_on,
        source=reading.source,
        note=reading.note,
        has_photo=bool(reading.photo_storage_url),
        photo_mime_type=reading.photo_mime_type,
        reported_by_user_id=reading.reported_by_user_id,
        reported_by_email=reported_by_email,
        created_at=reading.created_at,
    )


# --- meters -------------------------------------------------------------------


async def _valid_unit_ids(
    session: AsyncSession, *, organization_id: uuid.UUID, property_id: uuid.UUID
) -> set[uuid.UUID]:
    rows = await session.scalars(
        select(Unit.id).where(
            Unit.organization_id == organization_id,
            Unit.property_id == property_id,
            Unit.deleted_at.is_(None),
        )
    )
    return set(rows.all())


def _build_meter(
    *,
    organization_id: uuid.UUID,
    property_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    data: MeterCreate,
) -> Meter:
    return Meter(
        organization_id=organization_id,
        property_id=property_id,
        unit_id=data.unit_id,
        meter_number=data.meter_number.strip(),
        meter_type=data.meter_type,
        description=(data.description.strip() if data.description else None),
        location=(data.location.strip() if data.location else None),
        unit_label=(data.unit_label or _DEFAULT_UNIT_LABEL.get(data.meter_type)),
        installation_date=data.installation_date,
        calibration_valid_until=data.calibration_valid_until,
        reading_due_date=data.reading_due_date,
        supplier_name=(data.supplier_name.strip() if data.supplier_name else None),
        supplier_email=(str(data.supplier_email) if data.supplier_email else None),
        created_by_user_id=actor_id,
    )


async def create_meter(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    property_id: uuid.UUID,
    actor_id: uuid.UUID,
    data: MeterCreate,
) -> Meter:
    if data.unit_id is not None:
        valid = await _valid_unit_ids(
            session, organization_id=organization_id, property_id=property_id
        )
        if data.unit_id not in valid:
            raise MeterServiceError("Die gewählte Einheit gehört nicht zu dieser Liegenschaft.")

    meter = _build_meter(
        organization_id=organization_id,
        property_id=property_id,
        actor_id=actor_id,
        data=data,
    )
    session.add(meter)
    await session.flush()
    session.add(
        AuditLog(
            organization_id=organization_id,
            actor_user_id=actor_id,
            action="meter_created",
            target_type="meters",
            target_id=str(meter.id),
            payload_json={
                "property_id": str(property_id),
                "meter_number": meter.meter_number,
                "meter_type": meter.meter_type.value,
            },
        )
    )
    await session.commit()
    await session.refresh(meter)
    return meter


async def bulk_create_meters(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    property_id: uuid.UUID,
    actor_id: uuid.UUID,
    items: list[MeterCreate],
) -> tuple[list[Meter], list[MeterBulkCreateError]]:
    """Create many meters in one transaction. Per-row validation errors are
    collected (the valid rows still commit) so a single bad line in a pasted
    list doesn't sink the whole import."""
    valid_units = await _valid_unit_ids(
        session, organization_id=organization_id, property_id=property_id
    )
    created: list[Meter] = []
    errors: list[MeterBulkCreateError] = []
    for idx, item in enumerate(items):
        if item.unit_id is not None and item.unit_id not in valid_units:
            errors.append(
                MeterBulkCreateError(
                    index=idx,
                    meter_number=item.meter_number,
                    error="Einheit gehört nicht zu dieser Liegenschaft.",
                )
            )
            continue
        meter = _build_meter(
            organization_id=organization_id,
            property_id=property_id,
            actor_id=actor_id,
            data=item,
        )
        session.add(meter)
        created.append(meter)

    if created:
        await session.flush()
        session.add(
            AuditLog(
                organization_id=organization_id,
                actor_user_id=actor_id,
                action="meters_bulk_created",
                target_type="meters",
                target_id=str(property_id),
                payload_json={"property_id": str(property_id), "count": len(created)},
            )
        )
        await session.commit()
        for meter in created:
            await session.refresh(meter)
    return created, errors


async def update_meter(
    session: AsyncSession,
    *,
    meter: Meter,
    actor_id: uuid.UUID,
    data: MeterUpdate,
) -> Meter:
    changes = data.model_dump(exclude_unset=True)
    if "unit_id" in changes and changes["unit_id"] is not None:
        valid = await _valid_unit_ids(
            session,
            organization_id=meter.organization_id,
            property_id=meter.property_id,
        )
        if changes["unit_id"] not in valid:
            raise MeterServiceError("Die gewählte Einheit gehört nicht zu dieser Liegenschaft.")
    for field, value in changes.items():
        if field == "supplier_email" and value is not None:
            value = str(value)
        setattr(meter, field, value)
    session.add(
        AuditLog(
            organization_id=meter.organization_id,
            actor_user_id=actor_id,
            action="meter_updated",
            target_type="meters",
            target_id=str(meter.id),
            payload_json={"fields": sorted(changes.keys())},
        )
    )
    await session.commit()
    await session.refresh(meter)
    return meter


async def list_meters(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    property_id: uuid.UUID,
    include_inactive: bool = True,
) -> list[MeterResponse]:
    stmt = select(Meter).where(
        Meter.organization_id == organization_id,
        Meter.property_id == property_id,
    )
    if not include_inactive:
        stmt = stmt.where(Meter.is_active.is_(True))
    stmt = stmt.order_by(Meter.meter_type, Meter.description, Meter.meter_number)
    meters = list((await session.scalars(stmt)).all())
    if not meters:
        return []

    meter_ids = [m.id for m in meters]
    unit_ids = {m.unit_id for m in meters if m.unit_id}

    units: dict[uuid.UUID, Unit] = {}
    if unit_ids:
        unit_rows = (await session.scalars(select(Unit).where(Unit.id.in_(unit_ids)))).all()
        units = {u.id: u for u in unit_rows}

    count_rows = (
        await session.execute(
            select(MeterReading.meter_id, func.count())
            .where(MeterReading.meter_id.in_(meter_ids))
            .group_by(MeterReading.meter_id)
        )
    ).all()
    counts: dict[uuid.UUID, int] = {mid: int(c) for mid, c in count_rows}
    # Latest reading per meter via Postgres DISTINCT ON.
    latest_rows = (
        await session.scalars(
            select(MeterReading)
            .where(MeterReading.meter_id.in_(meter_ids))
            .distinct(MeterReading.meter_id)
            .order_by(
                MeterReading.meter_id,
                MeterReading.read_on.desc(),
                MeterReading.created_at.desc(),
            )
        )
    ).all()
    latest = {r.meter_id: r for r in latest_rows}

    return [
        to_meter_response(
            m,
            unit_name=(_unit_label(units[m.unit_id]) if m.unit_id in units else None),
            latest=latest.get(m.id),
            reading_count=int(counts.get(m.id, 0)),
        )
        for m in meters
    ]


async def get_meter(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    meter_id: uuid.UUID,
    property_id: uuid.UUID | None = None,
) -> Meter | None:
    stmt = select(Meter).where(
        Meter.id == meter_id,
        Meter.organization_id == organization_id,
    )
    if property_id is not None:
        stmt = stmt.where(Meter.property_id == property_id)
    meter: Meter | None = await session.scalar(stmt)
    return meter


async def meter_response(session: AsyncSession, *, meter: Meter) -> MeterResponse:
    """Enrich a single meter (unit name + reading count + latest) — used by
    the create/update endpoints so the SPA gets a complete row back."""
    unit_name: str | None = None
    if meter.unit_id is not None:
        unit = await session.get(Unit, meter.unit_id)
        unit_name = _unit_label(unit) if unit is not None else None
    count = (
        await session.scalar(
            select(func.count()).select_from(MeterReading).where(MeterReading.meter_id == meter.id)
        )
    ) or 0
    latest = await session.scalar(
        select(MeterReading)
        .where(MeterReading.meter_id == meter.id)
        .order_by(MeterReading.read_on.desc(), MeterReading.created_at.desc())
        .limit(1)
    )
    return to_meter_response(meter, unit_name=unit_name, latest=latest, reading_count=int(count))


async def reading_count_for_meter(session: AsyncSession, *, meter_id: uuid.UUID) -> int:
    count = await session.scalar(
        select(func.count()).select_from(MeterReading).where(MeterReading.meter_id == meter_id)
    )
    return int(count or 0)


# --- readings -----------------------------------------------------------------


async def create_reading(
    session: AsyncSession,
    *,
    meter: Meter,
    actor_id: uuid.UUID,
    value: Decimal,
    read_on: date,
    source: MeterReadingSource,
    settings: Settings,
    ocr_raw: str | None = None,
    note: str | None = None,
    photo: UploadFile | None = None,
) -> MeterReading:
    raw: bytes | None = None
    if photo is not None:
        raw = await photo.read()
        if len(raw) > settings.meter_reading_photo_max_bytes:
            max_mb = settings.meter_reading_photo_max_bytes // 1024 // 1024
            raise MeterServiceError(f"Foto darf höchstens {max_mb} MB groß sein.")

    reading = MeterReading(
        meter_id=meter.id,
        value=value,
        read_on=read_on,
        source=source,
        ocr_raw=ocr_raw,
        note=(note.strip() if note else None),
        reported_by_user_id=actor_id,
    )
    session.add(reading)
    await session.flush()  # need the id before picking a photo path

    if photo is not None and raw:
        try:
            _, suffix = write_photo(reading.id, photo.filename or "foto.jpg", raw)
        except MeterPhotoStorageError as exc:
            await session.rollback()
            raise MeterServiceError(str(exc)) from exc
        reading.photo_storage_url = f"local-disk:{suffix}"
        reading.photo_mime_type = photo.content_type

    session.add(
        AuditLog(
            organization_id=meter.organization_id,
            actor_user_id=actor_id,
            action="meter_reading_created",
            target_type="meter_readings",
            target_id=str(reading.id),
            payload_json={
                "meter_id": str(meter.id),
                "value": str(value),
                "source": source.value,
                "has_photo": bool(reading.photo_storage_url),
            },
        )
    )
    await session.commit()
    await session.refresh(reading)
    return reading


async def list_readings(
    session: AsyncSession, *, meter_id: uuid.UUID
) -> list[MeterReadingResponse]:
    rows = list(
        (
            await session.scalars(
                select(MeterReading)
                .where(MeterReading.meter_id == meter_id)
                .order_by(MeterReading.read_on.desc(), MeterReading.created_at.desc())
            )
        ).all()
    )
    reporter_ids = {r.reported_by_user_id for r in rows if r.reported_by_user_id}
    emails: dict[uuid.UUID, str] = {}
    if reporter_ids:
        user_rows = (await session.scalars(select(User).where(User.id.in_(reporter_ids)))).all()
        emails = {u.id: u.email for u in user_rows}
    return [
        to_reading_response(
            r,
            reported_by_email=(
                emails.get(r.reported_by_user_id) if r.reported_by_user_id else None
            ),
        )
        for r in rows
    ]


async def get_reading(
    session: AsyncSession, *, meter_id: uuid.UUID, reading_id: uuid.UUID
) -> MeterReading | None:
    reading: MeterReading | None = await session.scalar(
        select(MeterReading).where(
            MeterReading.id == reading_id,
            MeterReading.meter_id == meter_id,
        )
    )
    return reading


# --- OCR ----------------------------------------------------------------------


async def ocr_photo(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    image_bytes: bytes,
    mime_type: str,
    provider: LLMProvider | None = None,
) -> MeterReadingOCRResult:
    """OCR a meter photo into a suggested reading. Never fatal: if the
    provider is unconfigured or the model can't read the photo, return an
    empty suggestion so the client falls back to manual entry. Records one
    llm_audit row either way + commits it."""
    if provider is None:
        provider = get_llm_provider()
    try:
        result = await provider.extract_from_image(
            image_bytes=image_bytes,
            mime_type=mime_type,
            prompt=_OCR_PROMPT,
            response_schema=MeterReadingOCR,
        )
    except LLMProviderUnavailableError as exc:
        await llm_audit.record(
            session,
            organization_id=organization_id,
            purpose="meter.ocr_reading",
            provider=provider.name,
            status=llm_audit.status_for_exception(exc),
            error=str(exc),
        )
        await session.commit()
        return MeterReadingOCRResult(provider_available=False)
    except Exception as exc:
        await llm_audit.record(
            session,
            organization_id=organization_id,
            purpose="meter.ocr_reading",
            provider=provider.name,
            status=llm_audit.status_for_exception(exc),
            error=str(exc),
        )
        await session.commit()
        logger.warning("meter OCR failed: %s", exc)
        return MeterReadingOCRResult(provider_available=True)

    await llm_audit.record(
        session,
        organization_id=organization_id,
        purpose="meter.ocr_reading",
        provider=provider.name,
        status="ok",
        stats=result.stats,
    )
    await session.commit()
    payload = result.payload
    return MeterReadingOCRResult(
        suggested_value=_coerce_decimal(payload.reading),
        meter_number=payload.meter_number,
        confidence=payload.confidence,
        ocr_raw=payload.reading,
        provider_available=True,
    )


# --- CSV export ---------------------------------------------------------------


async def readings_csv_for_property(
    session: AsyncSession, *, organization_id: uuid.UUID, property_id: uuid.UUID
) -> str:
    """All readings for a property's meters as CSV — the Verwalter forwards
    this to the supplier out-of-band (v1 has no in-app send)."""
    rows = (
        await session.execute(
            select(MeterReading, Meter)
            .join(Meter, Meter.id == MeterReading.meter_id)
            .where(
                Meter.organization_id == organization_id,
                Meter.property_id == property_id,
            )
            .order_by(Meter.meter_number, MeterReading.read_on.desc())
        )
    ).all()

    reporter_ids = {r.reported_by_user_id for r, _ in rows if r.reported_by_user_id}
    emails: dict[uuid.UUID, str] = {}
    if reporter_ids:
        user_rows = (await session.scalars(select(User).where(User.id.in_(reporter_ids)))).all()
        emails = {u.id: u.email for u in user_rows}

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(
        [
            "Zählernummer",
            "Typ",
            "Beschreibung",
            "Einheit",
            "Wert",
            "Ablesedatum",
            "Quelle",
            "Notiz",
            "Erfasst von",
            "Erfasst am",
        ]
    )
    for reading, meter in rows:
        writer.writerow(
            [
                meter.meter_number,
                meter.meter_type.value,
                meter.description or "",
                meter.unit_label or "",
                f"{reading.value}",
                reading.read_on.isoformat(),
                reading.source.value,
                reading.note or "",
                emails.get(reading.reported_by_user_id, "") if reading.reported_by_user_id else "",
                reading.created_at.date().isoformat(),
            ]
        )
    return buf.getvalue()
