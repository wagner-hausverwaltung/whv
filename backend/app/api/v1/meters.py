"""Zähler (meter) endpoints — owner-facing (/me/...) + admin (/admin/...).

Both routers live here so the shared scoping helpers stay in one place;
they mount under different prefixes in main.py.

Admin (Verwalter):
  GET/POST  /admin/properties/{property_id}/meters        list / create
  POST      /admin/properties/{property_id}/meters/bulk   seed many at once
  GET       /admin/properties/{property_id}/meters/readings.csv
  PATCH/DEL /admin/meters/{meter_id}                       edit / remove
  GET/POST  /admin/meters/{meter_id}/readings             history / record
  GET       /admin/meters/{meter_id}/readings/{id}/photo  download photo

Member (any property member can report a reading):
  GET   /me/properties/{property_id}/meters               meters to report
  POST  /me/meters/{meter_id}/readings                    submit a reading
  POST  /me/meters/{meter_id}/readings/ocr                OCR a photo (preview)
  GET   /me/meters/{meter_id}/readings                    history
  GET   /me/meters/{meter_id}/readings/{id}/photo         download photo
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.me import _visible_properties_stmt
from app.auth.dependencies import get_current_user, require_role
from app.config import Settings, get_settings
from app.db import get_session
from app.integrations.storage.meter_readings import photo_path
from app.models import Meter, MeterReading, MeterReadingSource, Property, User, UserRole
from app.schemas.meter import (
    MeterBulkCreateRequest,
    MeterBulkCreateResponse,
    MeterCreate,
    MeterReadingOCRResult,
    MeterReadingResponse,
    MeterResponse,
    MeterUpdate,
)
from app.services import meters as meters_svc

me_router = APIRouter(prefix="/me", tags=["meters"])
admin_router = APIRouter(prefix="/admin", tags=["meters"])

_verwalter_only = require_role(UserRole.VERWALTER)


# --- shared helpers -----------------------------------------------------------


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


async def _admin_meter_or_404(session: AsyncSession, user: User, meter_id: uuid.UUID) -> Meter:
    meter = await meters_svc.get_meter(
        session, organization_id=user.organization_id, meter_id=meter_id
    )
    if meter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Zähler not found")
    return meter


async def _member_meter_or_404(
    session: AsyncSession, user: User, meter_id: uuid.UUID, *, require_active: bool = False
) -> Meter:
    """Resolve a meter the caller may see: it must belong to a property the
    user has access to (Verwalter → all; others → via active contracts).
    Same 404-on-no-access shape we use everywhere — never leak existence."""
    meter = await session.scalar(
        select(Meter).where(
            Meter.id == meter_id,
            Meter.organization_id == user.organization_id,
        )
    )
    if meter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Zähler not found")
    visible = await session.scalar(
        _visible_properties_stmt(user).where(Property.id == meter.property_id)
    )
    if visible is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Zähler not found")
    if require_active and not meter.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dieser Zähler ist nicht mehr aktiv.",
        )
    return meter


async def _resolve_reading_or_404(
    session: AsyncSession, *, meter: Meter, reading_id: uuid.UUID
) -> MeterReading:
    reading = await meters_svc.get_reading(session, meter_id=meter.id, reading_id=reading_id)
    if reading is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ablesung not found")
    return reading


def _photo_file_response(reading: MeterReading) -> FileResponse:
    if not reading.photo_storage_url or not reading.photo_storage_url.startswith("local-disk:"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Kein Foto zu dieser Ablesung."
        )
    suffix = reading.photo_storage_url[len("local-disk:") :]
    path = photo_path(reading.id, suffix)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Foto wurde nicht gefunden."
        )
    return FileResponse(
        path,
        media_type=reading.photo_mime_type or "image/jpeg",
        filename=f"zaehler-{reading.id.hex[:8]}{suffix}",
    )


# --- admin: meters ------------------------------------------------------------


@admin_router.get("/properties/{property_id}/meters", response_model=list[MeterResponse])
async def admin_list_meters(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[MeterResponse]:
    await _admin_property_or_404(session, current_user, property_id)
    return await meters_svc.list_meters(
        session,
        organization_id=current_user.organization_id,
        property_id=property_id,
        include_inactive=True,
    )


@admin_router.post(
    "/properties/{property_id}/meters",
    response_model=MeterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def admin_create_meter(
    property_id: uuid.UUID,
    req: MeterCreate,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MeterResponse:
    await _admin_property_or_404(session, current_user, property_id)
    try:
        meter = await meters_svc.create_meter(
            session,
            organization_id=current_user.organization_id,
            property_id=property_id,
            actor_id=current_user.id,
            data=req,
        )
    except meters_svc.MeterServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await meters_svc.meter_response(session, meter=meter)


@admin_router.post(
    "/properties/{property_id}/meters/bulk",
    response_model=MeterBulkCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def admin_bulk_create_meters(
    property_id: uuid.UUID,
    req: MeterBulkCreateRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MeterBulkCreateResponse:
    await _admin_property_or_404(session, current_user, property_id)
    created, errors = await meters_svc.bulk_create_meters(
        session,
        organization_id=current_user.organization_id,
        property_id=property_id,
        actor_id=current_user.id,
        items=req.meters,
    )
    return MeterBulkCreateResponse(
        created=[meters_svc.to_meter_response(m) for m in created],
        errors=errors,
    )


@admin_router.get("/properties/{property_id}/meters/readings.csv")
async def admin_export_readings_csv(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    await _admin_property_or_404(session, current_user, property_id)
    csv_text = await meters_svc.readings_csv_for_property(
        session,
        organization_id=current_user.organization_id,
        property_id=property_id,
    )
    filename = f"zaehlerstaende-{property_id.hex[:8]}.csv"
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@admin_router.patch("/meters/{meter_id}", response_model=MeterResponse)
async def admin_update_meter(
    meter_id: uuid.UUID,
    req: MeterUpdate,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MeterResponse:
    meter = await _admin_meter_or_404(session, current_user, meter_id)
    try:
        meter = await meters_svc.update_meter(
            session, meter=meter, actor_id=current_user.id, data=req
        )
    except meters_svc.MeterServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await meters_svc.meter_response(session, meter=meter)


@admin_router.delete("/meters/{meter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_meter(
    meter_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Hard-delete a meter — only when it has no readings yet (fixing a
    mistaken entry). A meter with history must be deactivated (PATCH
    is_active=false) instead, so the readings + their photos survive."""
    meter = await _admin_meter_or_404(session, current_user, meter_id)
    count = await meters_svc.reading_count_for_meter(session, meter_id=meter.id)
    if count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Zähler hat bereits Ablesungen — bitte deaktivieren statt löschen, "
                "damit die Historie erhalten bleibt."
            ),
        )
    await session.delete(meter)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- admin: readings ----------------------------------------------------------


@admin_router.get("/meters/{meter_id}/readings", response_model=list[MeterReadingResponse])
async def admin_list_readings(
    meter_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[MeterReadingResponse]:
    meter = await _admin_meter_or_404(session, current_user, meter_id)
    return await meters_svc.list_readings(session, meter_id=meter.id)


@admin_router.post(
    "/meters/{meter_id}/readings",
    response_model=MeterReadingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def admin_create_reading(
    meter_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    value: Annotated[Decimal, Form()],
    read_on: Annotated[date | None, Form()] = None,
    note: Annotated[str | None, Form()] = None,
    source: Annotated[MeterReadingSource, Form()] = MeterReadingSource.MANUAL,
    ocr_raw: Annotated[str | None, Form()] = None,
    photo: UploadFile | None = None,
) -> MeterReadingResponse:
    meter = await _admin_meter_or_404(session, current_user, meter_id)
    return await _do_create_reading(
        session=session,
        meter=meter,
        actor=current_user,
        settings=settings,
        value=value,
        read_on=read_on,
        note=note,
        source=source,
        ocr_raw=ocr_raw,
        photo=photo,
    )


@admin_router.get("/meters/{meter_id}/readings/{reading_id}/photo")
async def admin_download_reading_photo(
    meter_id: uuid.UUID,
    reading_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    meter = await _admin_meter_or_404(session, current_user, meter_id)
    reading = await _resolve_reading_or_404(session, meter=meter, reading_id=reading_id)
    return _photo_file_response(reading)


# --- member: meters + readings ------------------------------------------------


@me_router.get("/properties/{property_id}/meters", response_model=list[MeterResponse])
async def my_list_meters(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[MeterResponse]:
    prop = await session.scalar(
        _visible_properties_stmt(current_user).where(Property.id == property_id)
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Liegenschaft not found")
    # Members only see active meters; the Verwalter manages inactive ones in admin.
    return await meters_svc.list_meters(
        session,
        organization_id=current_user.organization_id,
        property_id=property_id,
        include_inactive=False,
    )


@me_router.post(
    "/meters/{meter_id}/readings",
    response_model=MeterReadingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def my_create_reading(
    meter_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    value: Annotated[Decimal, Form()],
    read_on: Annotated[date | None, Form()] = None,
    note: Annotated[str | None, Form()] = None,
    source: Annotated[MeterReadingSource, Form()] = MeterReadingSource.MANUAL,
    ocr_raw: Annotated[str | None, Form()] = None,
    photo: UploadFile | None = None,
) -> MeterReadingResponse:
    meter = await _member_meter_or_404(session, current_user, meter_id, require_active=True)
    return await _do_create_reading(
        session=session,
        meter=meter,
        actor=current_user,
        settings=settings,
        value=value,
        read_on=read_on,
        note=note,
        source=source,
        ocr_raw=ocr_raw,
        photo=photo,
    )


@me_router.post("/meters/{meter_id}/readings/ocr", response_model=MeterReadingOCRResult)
async def my_ocr_reading(
    meter_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    photo: UploadFile,
) -> MeterReadingOCRResult:
    """Upload a meter photo, get a suggested value back. Never fatal — an
    unconfigured provider or an unreadable photo returns an empty suggestion
    so the client just shows manual entry."""
    await _member_meter_or_404(session, current_user, meter_id, require_active=True)
    raw = await photo.read()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Leeres Foto.")
    if len(raw) > settings.meter_reading_photo_max_bytes:
        max_mb = settings.meter_reading_photo_max_bytes // 1024 // 1024
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Foto darf höchstens {max_mb} MB groß sein.",
        )
    return await meters_svc.ocr_photo(
        session,
        organization_id=current_user.organization_id,
        image_bytes=raw,
        mime_type=photo.content_type or "image/jpeg",
    )


@me_router.get("/meters/{meter_id}/readings", response_model=list[MeterReadingResponse])
async def my_list_readings(
    meter_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[MeterReadingResponse]:
    meter = await _member_meter_or_404(session, current_user, meter_id)
    return await meters_svc.list_readings(session, meter_id=meter.id)


@me_router.get("/meters/{meter_id}/readings/{reading_id}/photo")
async def my_download_reading_photo(
    meter_id: uuid.UUID,
    reading_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    meter = await _member_meter_or_404(session, current_user, meter_id)
    reading = await _resolve_reading_or_404(session, meter=meter, reading_id=reading_id)
    return _photo_file_response(reading)


# --- shared reading-create pipeline -------------------------------------------


async def _do_create_reading(
    *,
    session: AsyncSession,
    meter: Meter,
    actor: User,
    settings: Settings,
    value: Decimal,
    read_on: date | None,
    note: str | None,
    source: MeterReadingSource,
    ocr_raw: str | None,
    photo: UploadFile | None,
) -> MeterReadingResponse:
    if value < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Zählerstand darf nicht negativ sein."
        )
    try:
        reading = await meters_svc.create_reading(
            session,
            meter=meter,
            actor_id=actor.id,
            value=value,
            read_on=read_on or date.today(),
            source=source,
            settings=settings,
            ocr_raw=ocr_raw,
            note=note,
            photo=photo,
        )
    except meters_svc.MeterServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return meters_svc.to_reading_response(reading, reported_by_email=actor.email)
