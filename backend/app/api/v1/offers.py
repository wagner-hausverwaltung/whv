"""Offer (Angebot) generation endpoints (ADR-0019).

Verwalter-only. Phase 1 exposes a manual generator: POST a filled
OfferGenerateRequest, get back the rendered WEG/MV offer PDF. The inbound
auto-offer pipeline (Phase 2) reuses the same app.services.offers.generate_offer.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.config import Settings, get_settings
from app.db import get_session
from app.integrations.email.client import EmailClient, EmailError, get_email_client
from app.models import (
    AuditLog,
    OfferInquiry,
    OfferInquiryStatus,
    Organization,
    Trip,
    User,
    UserRole,
)
from app.schemas.offer import (
    OfferGenerateRequest,
    OfferInquiryDetailResponse,
    OfferInquiryFieldsUpdate,
    OfferInquiryNoteUpdate,
    OfferInquiryResponse,
    OfferLeadStatusUpdate,
    OfferSettingsResponse,
    OfferSettingsUpdate,
)
from app.services import offers as offers_svc
from app.services.offers import generate_offer

admin_router = APIRouter(prefix="/admin", tags=["offers"])

_verwalter_only = require_role(UserRole.VERWALTER)


async def _visits(
    session: AsyncSession, inquiry_ids: set[uuid.UUID]
) -> dict[uuid.UUID, tuple[datetime, int]]:
    """Besichtigungen per inquiry from the Fahrtenbuch: (end of the most
    recent linked trip, number of linked trips). Derived, never stored — a
    deleted mis-detected trip un-visits the inquiry again."""
    if not inquiry_ids:
        return {}
    last_visit = func.max(func.coalesce(Trip.ended_at, Trip.started_at))
    rows = await session.execute(
        select(Trip.inquiry_id, last_visit, func.count(Trip.id))
        .where(Trip.inquiry_id.in_(inquiry_ids))
        .group_by(Trip.inquiry_id)
    )
    return {iid: (when, int(n)) for iid, when, n in rows.all()}


async def _with_visits[InquiryOut: OfferInquiryResponse](
    session: AsyncSession, inquiries: list[OfferInquiry], model: type[InquiryOut]
) -> list[InquiryOut]:
    visits = await _visits(session, {i.id for i in inquiries})
    out: list[InquiryOut] = []
    for inq in inquiries:
        resp = model.model_validate(inq)
        if (v := visits.get(inq.id)) is not None:
            resp.visited_at, resp.visit_count = v
        out.append(resp)
    return out


async def _detail(session: AsyncSession, inquiry: OfferInquiry) -> OfferInquiryDetailResponse:
    return (await _with_visits(session, [inquiry], OfferInquiryDetailResponse))[0]


@admin_router.post("/offers/generate")
async def admin_generate_offer(
    payload: OfferGenerateRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
) -> Response:
    """Render a per-customer WEG/MV offer and return it as a PDF download."""
    try:
        pdf, filename = await asyncio.to_thread(generate_offer, payload)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@admin_router.get("/offer-settings", response_model=OfferSettingsResponse)
async def admin_get_offer_settings(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OfferSettingsResponse:
    """Read the org's anfragen@ "Auto-Modus" flag."""
    org = await session.get(Organization, current_user.organization_id)
    enabled = bool(org.offer_auto_send_enabled) if org is not None else False
    return OfferSettingsResponse(auto_send_enabled=enabled)


@admin_router.put("/offer-settings", response_model=OfferSettingsResponse)
async def admin_update_offer_settings(
    payload: OfferSettingsUpdate,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OfferSettingsResponse:
    """Toggle the org's "Auto-Modus". When on, future inbound inquiries that
    yield a valid offer are emailed automatically (no manual review)."""
    org = await session.get(Organization, current_user.organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    org.offer_auto_send_enabled = payload.auto_send_enabled
    await session.commit()
    return OfferSettingsResponse(auto_send_enabled=org.offer_auto_send_enabled)


@admin_router.get("/offer-inquiries", response_model=list[OfferInquiryResponse])
async def admin_list_offer_inquiries(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[OfferInquiryResponse]:
    """List inbound anfragen@ inquiries (newest first), optionally by status."""
    stmt = select(OfferInquiry).where(OfferInquiry.organization_id == current_user.organization_id)
    if status_filter:
        stmt = stmt.where(OfferInquiry.status == status_filter)
    # id (uuid7) is time-ordered, so it doubles as a deterministic tiebreak
    # when several inquiries share the same created_at (e.g. a seeded batch).
    stmt = stmt.order_by(OfferInquiry.created_at.desc(), OfferInquiry.id.desc()).limit(limit)
    inquiries = list((await session.scalars(stmt)).all())
    return await _with_visits(session, inquiries, OfferInquiryResponse)


@admin_router.post("/offer-inquiries/{inquiry_id}/send", response_model=OfferInquiryResponse)
async def admin_send_offer_inquiry(
    inquiry_id: uuid.UUID,
    payload: OfferGenerateRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OfferInquiryResponse:
    """Verwalter approves an inquiry: generate the offer from the reviewed
    fields and email it to the sender. Manual path — independent of the
    auto-send kill switch."""
    inquiry = await session.get(OfferInquiry, inquiry_id)
    if inquiry is None or inquiry.organization_id != current_user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inquiry not found")
    try:
        await offers_svc.email_offer_for_inquiry(
            inquiry, payload, email_client=email_client, settings=settings
        )
    except EmailError as exc:
        inquiry.status = OfferInquiryStatus.FAILED.value
        inquiry.error = str(exc)
        await session.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Send failed: {exc}") from exc
    await session.commit()
    await session.refresh(inquiry)
    return (await _with_visits(session, [inquiry], OfferInquiryResponse))[0]


@admin_router.put("/offer-inquiries/{inquiry_id}/lead-status", response_model=OfferInquiryResponse)
async def admin_set_offer_lead_status(
    inquiry_id: uuid.UUID,
    payload: OfferLeadStatusUpdate,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OfferInquiryResponse:
    """Set an inquiry's manual sales status (OPEN/ON_HOLD/ACCEPTED/DECLINED)."""
    inquiry = await session.get(OfferInquiry, inquiry_id)
    if inquiry is None or inquiry.organization_id != current_user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inquiry not found")
    inquiry.lead_status = payload.lead_status
    await session.commit()
    await session.refresh(inquiry)
    return (await _with_visits(session, [inquiry], OfferInquiryResponse))[0]


async def _get_owned_inquiry(
    session: AsyncSession, inquiry_id: uuid.UUID, current_user: User
) -> OfferInquiry:
    """Fetch an inquiry, 404 unless it belongs to the caller's org. Collapsing
    missing/foreign → 404 avoids disclosing existence across orgs."""
    inquiry = await session.get(OfferInquiry, inquiry_id)
    if inquiry is None or inquiry.organization_id != current_user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inquiry not found")
    return inquiry


@admin_router.delete("/offer-inquiries/{inquiry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_offer_inquiry(
    inquiry_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Remove an inquiry from the queue. Hard delete of the row (prospect PII —
    DSGVO erasure; any sent offer PDF was emailed, not persisted), plus a purge
    of its VERWALTER-only RAG card via the reindex task (which drops the card
    when the inquiry is gone). A PII-light AuditLog row records who deleted
    what state, matching the other destructive admin endpoints."""
    inquiry = await _get_owned_inquiry(session, inquiry_id, current_user)
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="offer_inquiry_deleted",
            target_type="offer_inquiries",
            target_id=str(inquiry.id),
            payload_json={
                "status": inquiry.status,
                "lead_status": inquiry.lead_status,
                "sent_at": inquiry.sent_at.isoformat() if inquiry.sent_at else None,
            },
        )
    )
    await session.delete(inquiry)
    await session.commit()
    if settings.rag_enabled:
        from app.workers.tasks import index_rag_masterdata

        index_rag_masterdata.delay(str(current_user.organization_id), str(inquiry_id), "anfrage")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("/offer-inquiries/{inquiry_id}", response_model=OfferInquiryDetailResponse)
async def admin_get_offer_inquiry(
    inquiry_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OfferInquiryDetailResponse:
    """Full detail for one inquiry — adds the raw email body, the shared note,
    and the error reason on top of the lean list fields."""
    return await _detail(session, await _get_owned_inquiry(session, inquiry_id, current_user))


@admin_router.put("/offer-inquiries/{inquiry_id}/fields", response_model=OfferInquiryDetailResponse)
async def admin_update_offer_fields(
    inquiry_id: uuid.UUID,
    payload: OfferInquiryFieldsUpdate,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OfferInquiryDetailResponse:
    """Correct the extracted inquiry fields (e.g. fill in a street + number the
    prospect didn't disclose initially). Overwrites the stored values so the
    list, the send dialog, and re-download all pick up the correction."""
    inquiry = await _get_owned_inquiry(session, inquiry_id, current_user)
    inquiry.art = payload.art
    inquiry.object_address = (payload.object_address or "").strip() or None
    inquiry.units = payload.units
    inquiry.desired_start = payload.desired_start
    await session.commit()
    await session.refresh(inquiry)
    return await _detail(session, inquiry)


@admin_router.put("/offer-inquiries/{inquiry_id}/note", response_model=OfferInquiryDetailResponse)
async def admin_set_offer_note(
    inquiry_id: uuid.UUID,
    payload: OfferInquiryNoteUpdate,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OfferInquiryDetailResponse:
    """Set the shared free-text note on an inquiry (visible to every Verwalter
    in the org)."""
    inquiry = await _get_owned_inquiry(session, inquiry_id, current_user)
    note = (payload.review_note or "").strip()
    inquiry.review_note = note or None
    await session.commit()
    await session.refresh(inquiry)
    return await _detail(session, inquiry)


@admin_router.post(
    "/offer-inquiries/{inquiry_id}/reminder", response_model=OfferInquiryDetailResponse
)
async def admin_send_offer_reminder(
    inquiry_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OfferInquiryDetailResponse:
    """Email a friendly follow-up reminder to the prospect. Only valid once the
    offer has actually been sent — and a failed reminder must NOT corrupt the
    original SENT state, so we never flip the inquiry to FAILED here."""
    inquiry = await _get_owned_inquiry(session, inquiry_id, current_user)
    if inquiry.status != OfferInquiryStatus.SENT.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Reminder only available after the offer was sent"
        )
    try:
        await offers_svc.send_reminder_for_inquiry(
            inquiry, email_client=email_client, settings=settings
        )
    except EmailError as exc:
        # Do not touch status/sent_at — the original offer is still validly sent.
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Reminder failed: {exc}") from exc
    await session.commit()
    await session.refresh(inquiry)
    return await _detail(session, inquiry)


def _redownload_request(inquiry: OfferInquiry) -> OfferGenerateRequest:
    """Reconstruct the OfferGenerateRequest for a re-download. Prefers the exact
    as-sent JSON; falls back to the stored extracted fields for offers sent
    before that was persisted (WEG only — MV recipient fields weren't stored)."""
    if inquiry.sent_request_json:
        return OfferGenerateRequest.model_validate_json(inquiry.sent_request_json)
    if inquiry.art not in ("WEG", "MV", "SEV") or not inquiry.units:
        raise ValueError("Keine gespeicherten Angebotsdaten zum Neu-Erzeugen")
    if inquiry.art in ("MV", "SEV"):
        # Legacy MV/SEV offers didn't persist the recipient → can't rebuild.
        # (Post-2026 sends always carry sent_request_json, handled above.)
        raise ValueError(
            f"{inquiry.art}-Angebot kann ohne gespeicherte Daten nicht neu erzeugt werden"
        )
    return OfferGenerateRequest(
        art="WEG",
        units=inquiry.units,
        start_date=inquiry.desired_start,
        object_street=inquiry.object_address or None,
    )


@admin_router.get("/offer-inquiries/{inquiry_id}/offer.pdf")
async def admin_download_offer(
    inquiry_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Re-download the generated offer for a sent inquiry. The PDF isn't stored;
    it's regenerated from the exact as-sent request (or, for legacy offers, the
    stored extracted fields)."""
    inquiry = await _get_owned_inquiry(session, inquiry_id, current_user)
    download_name = inquiry.generated_offer_filename
    if not download_name:
        raise HTTPException(status.HTTP_409_CONFLICT, "No offer has been sent for this inquiry")
    try:
        req = _redownload_request(inquiry)
        pdf, _ = await asyncio.to_thread(generate_offer, req)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )
