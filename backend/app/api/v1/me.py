import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user
from app.config import Settings, get_settings
from app.db import get_session
from app.integrations.storage.avatars import AvatarError, delete_avatar, write_avatar
from app.integrations.storage.documents import document_path
from app.models import (
    AuditLog,
    Contact,
    Contract,
    ContractContact,
    Document,
    DocumentFolder,
    Property,
    Unit,
    User,
    UserRole,
)
from app.models import (
    Session as DbSession,
)
from app.schemas.auth import UserResponse
from app.schemas.document import DocumentFolderResponse, DocumentResponse
from app.schemas.property import PropertyDetailResponse, PropertyResponse
from app.schemas.unit import UnitResponse

router = APIRouter(prefix="/me", tags=["me"])


def _to_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        role=user.role.value,
        organization_id=user.organization_id,
        contact_id_impower=user.contact_id_impower,
        avatar_url=user.avatar_url,
    )


@router.get("", response_model=UserResponse)
async def get_me(current_user: Annotated[User, Depends(get_current_user)]) -> UserResponse:
    return _to_user_response(current_user)


@router.put("/avatar", response_model=UserResponse)
async def upload_avatar(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: UploadFile,
) -> UserResponse:
    """Upload (or replace) the caller's avatar image.

    Accepts JPEG/PNG/WebP/GIF/BMP up to `settings.avatar_max_bytes`; Pillow
    normalises every upload to a 256x256 PNG. The stored URL carries a
    cache-bust `?v={mtime}` query so SPA refreshes pick up changes.
    """
    raw = await file.read()
    if len(raw) > settings.avatar_max_bytes:
        max_mb = settings.avatar_max_bytes // 1024 // 1024
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Avatar darf höchstens {max_mb} MB groß sein.",
        )
    try:
        url = write_avatar(current_user.id, raw)
    except AvatarError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ungültige Bilddatei: {exc}",
        ) from exc

    current_user.avatar_url = url
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="avatar_updated",
            target_type="users",
            target_id=str(current_user.id),
            payload_json={"size_bytes": len(raw)},
        )
    )
    await session.commit()
    await session.refresh(current_user)
    return _to_user_response(current_user)


@router.delete("/avatar", response_model=UserResponse)
async def remove_avatar(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserResponse:
    """Remove the caller's avatar — Layout falls back to initials."""
    delete_avatar(current_user.id)
    current_user.avatar_url = None
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="avatar_deleted",
            target_type="users",
            target_id=str(current_user.id),
            payload_json={},
        )
    )
    await session.commit()
    await session.refresh(current_user)
    return _to_user_response(current_user)


def _visible_properties_stmt(user: User):  # type: ignore[no-untyped-def]
    """Build a SELECT statement for properties visible to the given user.

    VERWALTER sees all org properties; other roles are scoped via
    contact_id_impower → contract_contacts → contracts → properties.
    """
    base = select(Property).where(
        Property.organization_id == user.organization_id,
        Property.deleted_at.is_(None),
    )
    if user.role == UserRole.VERWALTER:
        return base
    return (
        base.join(Contract, Contract.property_id == Property.id)
        .join(ContractContact, ContractContact.contract_id == Contract.id)
        .join(Contact, Contact.id == ContractContact.contact_id)
        .where(Contact.impower_id == user.contact_id_impower)
        .distinct()
    )


@router.get("/properties", response_model=list[PropertyResponse])
async def get_my_properties(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[PropertyResponse]:
    if current_user.role != UserRole.VERWALTER and current_user.contact_id_impower is None:
        return []
    stmt = _visible_properties_stmt(current_user).order_by(Property.name)
    rows = (await session.scalars(stmt)).all()
    return [PropertyResponse.model_validate(p) for p in rows]


@router.get("/properties/{property_id}", response_model=PropertyDetailResponse)
async def get_my_property(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PropertyDetailResponse:
    if current_user.role != UserRole.VERWALTER and current_user.contact_id_impower is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    stmt = _visible_properties_stmt(current_user).where(Property.id == property_id)
    prop = await session.scalar(stmt)
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    unit_rows = (
        await session.scalars(
            select(Unit)
            .where(Unit.property_id == prop.id, Unit.deleted_at.is_(None))
            .order_by(Unit.unit_rank.nulls_last(), Unit.unit_hr_id)
        )
    ).all()

    return PropertyDetailResponse(
        **PropertyResponse.model_validate(prop).model_dump(),
        units=[UnitResponse.model_validate(u) for u in unit_rows],
    )


@router.get("/properties/{property_id}/documents", response_model=list[DocumentResponse])
async def get_my_property_documents(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DocumentResponse]:
    if current_user.role != UserRole.VERWALTER and current_user.contact_id_impower is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    # Reuse the same scope check as /me/properties/{id}: if the property isn't visible,
    # return 404 (not 403) so we don't leak existence.
    prop_stmt = _visible_properties_stmt(current_user).where(Property.id == property_id)
    prop = await session.scalar(prop_stmt)
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    doc_rows = (
        await session.scalars(
            select(Document)
            .where(Document.property_id == prop.id, Document.deleted_at.is_(None))
            .order_by(Document.issued_date.desc().nulls_last(), Document.name)
        )
    ).all()

    return [DocumentResponse.model_validate(d) for d in doc_rows]


@router.get(
    "/properties/{property_id}/folders",
    response_model=list[DocumentFolderResponse],
)
async def get_my_property_folders(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DocumentFolderResponse]:
    """Read-only folder tree for the portal. Same 404-on-no-access
    behaviour as `/me/properties/{id}/documents` so we don't leak
    existence of a folder under a property the caller can't see."""
    if current_user.role != UserRole.VERWALTER and current_user.contact_id_impower is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")
    prop_stmt = _visible_properties_stmt(current_user).where(Property.id == property_id)
    prop = await session.scalar(prop_stmt)
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")
    rows = (
        await session.scalars(
            select(DocumentFolder)
            .where(
                DocumentFolder.property_id == prop.id,
                DocumentFolder.deleted_at.is_(None),
            )
            .order_by(DocumentFolder.name)
        )
    ).all()
    return [DocumentFolderResponse.model_validate(f) for f in rows]


@router.get("/documents/{document_id}/file")
async def download_my_document(
    document_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    """Authenticated PDF download for portal users.

    Scope: the document must belong to a property the caller can see
    (same `_visible_properties_stmt` rule used elsewhere). Verwalter
    sees everything; other roles are filtered to their contracts.

    Visibility on the document is not yet gated here — current behaviour
    matches `/me/properties/{id}/documents` which surfaces every non-
    deleted doc for the property. Tightening to per-role visibility is
    deliberately deferred until the portal has UI for it.
    """
    doc = await session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.organization_id == current_user.organization_id,
            Document.deleted_at.is_(None),
        )
    )
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Property-scope check (skipped for Verwalter — they see everything).
    if current_user.role != UserRole.VERWALTER and doc.property_id is not None:
        prop_stmt = _visible_properties_stmt(current_user).where(Property.id == doc.property_id)
        prop = await session.scalar(prop_stmt)
        if prop is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if not doc.storage_url or not doc.storage_url.startswith("local-disk:"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Datei ist nicht lokal hinterlegt.",
        )
    suffix = doc.storage_url[len("local-disk:") :]
    path = document_path(doc.id, suffix)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Datei wurde nicht gefunden.",
        )
    return FileResponse(
        path,
        media_type=doc.mime_type or "application/octet-stream",
        filename=f"{doc.name}{suffix}",
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Soft-delete the current user. Spec §7.3: 30-day recovery window.

    Effect:
    - users.deleted_at = now (auth dependency rejects further requests)
    - All non-revoked sessions for this user → revoked_at = now (refresh tokens dead)
    - Audit row written
    - One commit, all-or-nothing

    Hard-delete after the 30-day window is a future operational job
    (not implemented in v1 of this endpoint).
    """
    now = datetime.now(UTC)

    current_user.deleted_at = now

    await session.execute(
        update(DbSession)
        .where(DbSession.user_id == current_user.id, DbSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )

    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="user_self_delete",
            target_type="users",
            target_id=str(current_user.id),
        )
    )

    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/export")
async def export_me(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JSONResponse:
    """DSGVO Art. 20 (portability) — return the user's personal data as JSON.

    Includes only data *about the user*: their profile, their sessions
    (metadata, never the token hashes), and audit entries where they were
    the actor. Organizational data (properties, documents, contacts they
    have *access* to) is intentionally out of scope — it's not their
    personal data under GDPR.
    """
    sessions = (
        await session.scalars(
            select(DbSession)
            .where(DbSession.user_id == current_user.id)
            .order_by(DbSession.created_at.desc())
        )
    ).all()

    audit_rows = (
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.actor_user_id == current_user.id)
            .order_by(AuditLog.created_at.desc())
        )
    ).all()

    payload: dict[str, object] = {
        "exported_at": datetime.now(UTC).isoformat(),
        "format_version": "1.0",
        "user": {
            "id": str(current_user.id),
            "organization_id": str(current_user.organization_id),
            "email": current_user.email,
            "role": current_user.role.value,
            "contact_id_impower": current_user.contact_id_impower,
            "locale": current_user.locale,
            "last_login_at": (
                current_user.last_login_at.isoformat() if current_user.last_login_at else None
            ),
            "created_at": current_user.created_at.isoformat(),
            "updated_at": current_user.updated_at.isoformat(),
            "deleted_at": (
                current_user.deleted_at.isoformat() if current_user.deleted_at else None
            ),
            # password_hash, sign_in_with_apple_sub, mfa_secret intentionally omitted.
        },
        "sessions": [
            {
                "id": str(s.id),
                "expires_at": s.expires_at.isoformat(),
                "user_agent": s.user_agent,
                "ip_hash": s.ip_hash,
                "last_used_at": s.last_used_at.isoformat() if s.last_used_at else None,
                "revoked_at": s.revoked_at.isoformat() if s.revoked_at else None,
                "created_at": s.created_at.isoformat(),
                # refresh_token_hash intentionally omitted.
            }
            for s in sessions
        ],
        "audit_log_entries": [
            {
                "id": str(a.id),
                "action": a.action,
                "target_type": a.target_type,
                "target_id": a.target_id,
                "payload": a.payload_json,
                "created_at": a.created_at.isoformat(),
            }
            for a in audit_rows
        ],
    }

    filename = f"whv-export-{current_user.id}-{datetime.now(UTC).date().isoformat()}.json"
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# selectinload import is kept for future N+1 mitigation; silence unused-import.
_ = selectinload
