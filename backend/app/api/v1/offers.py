"""Offer (Angebot) generation endpoints (ADR-0019).

Verwalter-only. Phase 1 exposes a manual generator: POST a filled
OfferGenerateRequest, get back the rendered WEG/MV offer PDF. The inbound
auto-offer pipeline (Phase 2) reuses the same app.services.offers.generate_offer.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.auth.dependencies import require_role
from app.models import User, UserRole
from app.schemas.offer import OfferGenerateRequest
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
