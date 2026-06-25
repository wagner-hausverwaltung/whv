"""Offer (Angebot) generation endpoints (ADR-0019).

Verwalter-only. Phase 1 exposes a manual generator: POST a filled
OfferGenerateRequest, get back the rendered WEG/MV offer PDF. The inbound
auto-offer pipeline (Phase 2) reuses the same app.services.offers.generate_offer.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.config import Settings, get_settings
from app.db import get_session
from app.integrations.email.client import EmailClient, EmailError, get_email_client
from app.models import OfferInquiry, OfferInquiryStatus, User, UserRole
from app.schemas.offer import OfferGenerateRequest, OfferInquiryResponse
from app.services import offers as offers_svc
from app.services.offers import generate_offer

admin_router = APIRouter(prefix="/admin", tags=["offers"])

_verwalter_only = require_role(UserRole.VERWALTER)


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


@admin_router.get("/offer-inquiries", response_model=list[OfferInquiryResponse])
async def admin_list_offer_inquiries(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[OfferInquiry]:
    """List inbound anfragen@ inquiries (newest first), optionally by status."""
    stmt = select(OfferInquiry).where(OfferInquiry.organization_id == current_user.organization_id)
    if status_filter:
        stmt = stmt.where(OfferInquiry.status == status_filter)
    stmt = stmt.order_by(OfferInquiry.created_at.desc()).limit(limit)
    return list((await session.scalars(stmt)).all())


@admin_router.post("/offer-inquiries/{inquiry_id}/send", response_model=OfferInquiryResponse)
async def admin_send_offer_inquiry(
    inquiry_id: uuid.UUID,
    payload: OfferGenerateRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OfferInquiry:
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
    return inquiry
