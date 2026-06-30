"""Jahresabrechnung tracker endpoints.

- Member read: ``GET /me/properties/{id}/accounting`` — any owner/tenant on a
  visible property sees the (read-only) stage progress.
- Verwalter write: ``PUT /admin/properties/{id}/accounting/{year}/stages/{code}``
  — tick / untick one stage.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.me import _visible_properties_stmt
from app.auth.dependencies import get_current_user, require_role
from app.db import get_session
from app.models import Property, User, UserRole
from app.schemas.accounting import AccountingProgressResponse, AccountingStageUpdate
from app.services import accounting as accounting_svc

me_router = APIRouter(prefix="/me", tags=["accounting"])
admin_router = APIRouter(prefix="/admin", tags=["accounting"])

_verwalter_only = require_role(UserRole.VERWALTER)


@me_router.get("/properties/{property_id}/accounting", response_model=AccountingProgressResponse)
async def get_my_property_accounting(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    year: Annotated[int | None, Query()] = None,
) -> AccountingProgressResponse:
    """Stage progress for one property's Wirtschaftsjahr (read-only). Defaults to
    the active accounting year (last calendar year). Property must be in the
    caller's visible set; 404 otherwise (no existence disclosure)."""
    if current_user.role != UserRole.VERWALTER and current_user.contact_id_impower is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")
    prop = await session.scalar(
        _visible_properties_stmt(current_user).where(Property.id == property_id)
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")
    y = year if year is not None else accounting_svc.active_accounting_year()
    return await accounting_svc.get_progress(session, property_id=property_id, year=y)


@admin_router.put(
    "/properties/{property_id}/accounting/{year}/stages/{code}",
    response_model=AccountingProgressResponse,
)
async def set_property_accounting_stage(
    property_id: uuid.UUID,
    year: int,
    code: str,
    payload: AccountingStageUpdate,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AccountingProgressResponse:
    """Tick / untick one stage (A-I) for a property's Wirtschaftsjahr."""
    prop = await session.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.organization_id == current_user.organization_id,
            Property.deleted_at.is_(None),
        )
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")
    try:
        return await accounting_svc.set_stage(
            session,
            property_id=property_id,
            organization_id=current_user.organization_id,
            year=year,
            code=code.upper(),
            done=payload.done,
            note=payload.note,
            user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
