"""Vollmacht (ETV proxy) endpoints — owner-facing (/me) + admin register.

Member (Eigentümer/Beirat — the voters):
  POST /me/assemblies/{id}/vollmacht        grant + sign (multipart)
  GET  /me/assemblies/{id}/vollmacht        my active Vollmacht (404 = none)
  POST /me/vollmachten/{id}/revoke          withdraw before the meeting
  GET  /me/vollmachten/{id}/document.pdf    download my signed Vollmacht

Admin (Verwalter):
  GET  /admin/assemblies/{id}/vollmachten   proxy register for the meeting
  GET  /admin/vollmachten/{id}/document.pdf download any Vollmacht
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.me import _visible_properties_stmt
from app.auth.dependencies import get_current_user, require_role
from app.config import Settings, get_settings
from app.db import get_session
from app.models import EtvAssembly, EtvVollmacht, Property, User, UserRole
from app.schemas.vollmacht import VollmachtResponse
from app.services import vollmachten as vollmachten_svc

me_router = APIRouter(prefix="/me", tags=["vollmachten"])
admin_router = APIRouter(prefix="/admin", tags=["vollmachten"])

_verwalter_only = require_role(UserRole.VERWALTER)
# Only owners vote at an ETV, so only they may delegate a proxy.
_OWNER_ROLES = {UserRole.EIGENTUEMER, UserRole.BEIRAT}


async def _member_assembly_or_404(
    session: AsyncSession, user: User, assembly_id: uuid.UUID
) -> EtvAssembly:
    assembly = await session.scalar(
        select(EtvAssembly).where(
            EtvAssembly.id == assembly_id,
            EtvAssembly.organization_id == user.organization_id,
            EtvAssembly.deleted_at.is_(None),
        )
    )
    if assembly is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Versammlung not found")
    visible = await session.scalar(
        _visible_properties_stmt(user).where(Property.id == assembly.property_id)
    )
    if visible is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Versammlung not found")
    return assembly


async def _admin_assembly_or_404(
    session: AsyncSession, user: User, assembly_id: uuid.UUID
) -> EtvAssembly:
    assembly = await session.scalar(
        select(EtvAssembly).where(
            EtvAssembly.id == assembly_id,
            EtvAssembly.organization_id == user.organization_id,
            EtvAssembly.deleted_at.is_(None),
        )
    )
    if assembly is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Versammlung not found")
    return assembly


def _pdf_response(settings: Settings, vollmacht: EtvVollmacht) -> FileResponse:
    if not vollmacht.pdf_storage_url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Keine PDF vorhanden.")
    path = vollmachten_svc.pdf_path(settings, vollmacht.id)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="PDF wurde nicht gefunden."
        )
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"vollmacht-{vollmacht.id.hex[:8]}.pdf",
    )


# --- member ------------------------------------------------------------------


@me_router.post(
    "/assemblies/{assembly_id}/vollmacht",
    response_model=VollmachtResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_my_vollmacht(
    assembly_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    proxy_name: Annotated[str, Form()],
    scope_note: Annotated[str | None, Form()] = None,
    signature: UploadFile | None = None,
) -> VollmachtResponse:
    if current_user.role not in _OWNER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nur Eigentümer:innen können eine Vollmacht erteilen.",
        )
    assembly = await _member_assembly_or_404(session, current_user, assembly_id)

    sig: bytes | None = None
    if signature is not None:
        raw = await signature.read()
        if raw:
            if len(raw) > settings.vollmacht_signature_max_bytes:
                max_mb = settings.vollmacht_signature_max_bytes // 1024 // 1024
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Unterschrift darf höchstens {max_mb} MB groß sein.",
                )
            sig = raw

    try:
        vollmacht = await vollmachten_svc.create_vollmacht(
            session,
            assembly=assembly,
            actor=current_user,
            proxy_name=proxy_name,
            scope_note=scope_note,
            signature_png=sig,
            settings=settings,
        )
    except vollmachten_svc.VollmachtServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return vollmachten_svc.to_response(vollmacht, principal_email=current_user.email)


@me_router.get("/assemblies/{assembly_id}/vollmacht", response_model=VollmachtResponse)
async def get_my_vollmacht(
    assembly_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VollmachtResponse:
    """My active Vollmacht for this assembly. 404 = none yet (the client
    shows the 'grant' action)."""
    await _member_assembly_or_404(session, current_user, assembly_id)
    vollmacht = await vollmachten_svc.get_active_for_user(
        session, assembly_id=assembly_id, user_id=current_user.id
    )
    if vollmacht is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Keine Vollmacht")
    return vollmachten_svc.to_response(vollmacht, principal_email=current_user.email)


async def _own_vollmacht_or_404(
    session: AsyncSession, user: User, vollmacht_id: uuid.UUID
) -> EtvVollmacht:
    vollmacht = await vollmachten_svc.get_vollmacht(
        session, vollmacht_id=vollmacht_id, organization_id=user.organization_id
    )
    if vollmacht is None or vollmacht.principal_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vollmacht not found")
    return vollmacht


@me_router.post("/vollmachten/{vollmacht_id}/revoke", response_model=VollmachtResponse)
async def revoke_my_vollmacht(
    vollmacht_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VollmachtResponse:
    vollmacht = await _own_vollmacht_or_404(session, current_user, vollmacht_id)
    vollmacht = await vollmachten_svc.revoke_vollmacht(
        session, vollmacht=vollmacht, actor_id=current_user.id
    )
    return vollmachten_svc.to_response(vollmacht, principal_email=current_user.email)


@me_router.get("/vollmachten/{vollmacht_id}/document.pdf")
async def download_my_vollmacht(
    vollmacht_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    vollmacht = await _own_vollmacht_or_404(session, current_user, vollmacht_id)
    return _pdf_response(settings, vollmacht)


# --- admin -------------------------------------------------------------------


@admin_router.get("/assemblies/{assembly_id}/vollmachten", response_model=list[VollmachtResponse])
async def admin_list_vollmachten(
    assembly_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[VollmachtResponse]:
    await _admin_assembly_or_404(session, current_user, assembly_id)
    return await vollmachten_svc.list_for_assembly(session, assembly_id=assembly_id)


@admin_router.get("/vollmachten/{vollmacht_id}/document.pdf")
async def admin_download_vollmacht(
    vollmacht_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    vollmacht = await vollmachten_svc.get_vollmacht(
        session, vollmacht_id=vollmacht_id, organization_id=current_user.organization_id
    )
    if vollmacht is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vollmacht not found")
    return _pdf_response(settings, vollmacht)
