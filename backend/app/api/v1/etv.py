"""Eigentümerversammlung (ETV) endpoints — owner (/me) + admin (/admin).

Two routers exported from this module:

  me_router     — read-only ETV access for portal / iOS owner views
  admin_router  — Verwalter-only CRUD on assembly + agenda + discussion +
                  signed-protocol PDF upload

The owner side intentionally has no mutation routes — for an in-person
assembly, the owner doesn't vote in the portal (the signed protocol is
the record). They just read past + planned ETVs and download the PDF.

Storage for the protocol PDF mirrors the announcement-attachment
pattern: a local-disk path under `settings.etv_protocol_dir` until
Hetzner Object Storage lands. The PDF is served back through an
authenticated FileResponse so we can re-check scope on every download.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.me import _visible_properties_stmt
from app.auth.dependencies import get_current_user, require_role
from app.config import Settings, get_settings
from app.db import get_session
from app.models import (
    AgendaItemType,
    AuditLog,
    EtvAgendaItem,
    EtvAssembly,
    EtvAssemblyComment,
    EtvDiscussionEntry,
    Property,
    User,
    UserRole,
)
from app.schemas.etv import (
    AgendaItemResponse,
    AssemblyCommentResponse,
    AssemblyDetailResponse,
    AssemblyResponse,
    CreateAgendaItemRequest,
    CreateAssemblyCommentRequest,
    CreateAssemblyRequest,
    CreateDiscussionEntryRequest,
    DiscussionEntryResponse,
    InvitationUploadResponse,
    ProtocolUploadResponse,
    UpdateAgendaItemRequest,
    UpdateAssemblyCommentRequest,
    UpdateAssemblyRequest,
)
from app.services import etv as svc

logger = logging.getLogger(__name__)

me_router = APIRouter(prefix="/me", tags=["etv"])
admin_router = APIRouter(prefix="/admin", tags=["etv"])

_verwalter_only = require_role(UserRole.VERWALTER)


# ---------- helpers ----------


def _assembly_to_list_response(a: EtvAssembly, prop: Property | None = None) -> AssemblyResponse:
    """List-view builder. `prop` is optional so legacy callers stay
    valid; new callers pre-fetch in a single batched SELECT and pass
    it through so the response carries property_name +
    property_hr_id without a per-row round-trip."""
    resp = AssemblyResponse.model_validate(a)
    if prop is not None:
        resp.property_name = prop.name
        resp.property_hr_id = prop.property_hr_id
    return resp


async def _props_by_id_for(
    session: AsyncSession, assemblies: list[EtvAssembly]
) -> dict[uuid.UUID, Property]:
    """Batch-fetch the Property rows for a list of assemblies.

    One SELECT in IN(...) keyed by property_id. Returns {} if the
    input list is empty. Used by every endpoint that returns a list
    of assemblies — keeps property_name + property_hr_id on the
    response cheap regardless of list size.
    """
    if not assemblies:
        return {}
    prop_ids = {a.property_id for a in assemblies}
    rows = (
        (await session.execute(select(Property).where(Property.id.in_(prop_ids)))).scalars().all()
    )
    return {p.id: p for p in rows}


async def _assembly_to_detail(session: AsyncSession, a: EtvAssembly) -> AssemblyDetailResponse:
    """Compose the full nested tree for one assembly in two extra
    queries (items, then a single batched discussion fetch keyed by
    item id). Used by both `/me/assemblies/{id}` + the admin variant."""
    items = await svc.load_agenda_items(session, assembly_id=a.id)
    disc_by_item = await svc.load_discussion_for_items(
        session, agenda_item_ids=[i.id for i in items]
    )
    item_responses = [
        AgendaItemResponse(
            id=i.id,
            assembly_id=i.assembly_id,
            position=i.position,
            type=i.type,
            title=i.title,
            body=i.body,
            beschluss_text=i.beschluss_text,
            vote_yes=i.vote_yes,
            vote_no=i.vote_no,
            vote_abstain=i.vote_abstain,
            vote_required_quorum=i.vote_required_quorum,
            vote_result=i.vote_result,
            voting_basis=i.voting_basis,
            present_count=i.present_count,
            discussion=[
                DiscussionEntryResponse.model_validate(d) for d in disc_by_item.get(i.id, [])
            ],
        )
        for i in items
    ]
    prop = await session.get(Property, a.property_id)
    return AssemblyDetailResponse(
        id=a.id,
        property_id=a.property_id,
        property_name=prop.name if prop else None,
        property_hr_id=prop.property_hr_id if prop else None,
        title=a.title,
        description=a.description,
        status=a.status,
        scheduled_start=a.scheduled_start,
        scheduled_end=a.scheduled_end,
        actual_start=a.actual_start,
        actual_end=a.actual_end,
        location=a.location,
        teams_meeting_url=a.teams_meeting_url,
        invitation_pdf_url=a.invitation_pdf_url,
        invitation_uploaded_at=a.invitation_uploaded_at,
        auto_extracted_at=a.auto_extracted_at,
        protocol_extracted_at=a.protocol_extracted_at,
        verified_at=a.verified_at,
        protocol_verified_at=a.protocol_verified_at,
        agenda_pdf_url=a.agenda_pdf_url,
        protocol_pdf_url=a.protocol_pdf_url,
        protocol_uploaded_at=a.protocol_uploaded_at,
        created_at=a.created_at,
        agenda_items=item_responses,
    )


# =================================================================
# Owner / portal-user side — read-only
# =================================================================


@me_router.get(
    "/properties/{property_id}/assemblies",
    response_model=list[AssemblyResponse],
)
async def list_my_property_assemblies(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AssemblyResponse]:
    """All non-cancelled assemblies for one of the caller's properties.

    Same 404-on-no-access shape as `/me/properties/{id}/documents` so we
    don't leak existence of a property the caller can't see.
    """
    if current_user.role != UserRole.VERWALTER and current_user.contact_id_impower is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")
    prop = await session.scalar(
        _visible_properties_stmt(current_user).where(Property.id == property_id)
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    rows = await svc.list_assemblies_for_property(
        session,
        organization_id=current_user.organization_id,
        property_id=prop.id,
        include_cancelled=False,
    )
    props = await _props_by_id_for(session, rows)
    return [_assembly_to_list_response(a, props.get(a.property_id)) for a in rows]


@me_router.get("/assemblies/{assembly_id}", response_model=AssemblyDetailResponse)
async def get_my_assembly(
    assembly_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssemblyDetailResponse:
    """Detail view with full agenda + discussion. Scope-checked via
    the visible-properties statement — owners only see assemblies
    attached to a property they have a contract on."""
    a = await svc.load_assembly_for_org(
        session,
        organization_id=current_user.organization_id,
        assembly_id=assembly_id,
    )
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assembly not found")
    # Property visibility check — same idea as the documents endpoint.
    if current_user.role != UserRole.VERWALTER:
        if current_user.contact_id_impower is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assembly not found")
        visible = await session.scalar(
            _visible_properties_stmt(current_user).where(Property.id == a.property_id)
        )
        if visible is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assembly not found")
    return await _assembly_to_detail(session, a)


@me_router.get("/assemblies/{assembly_id}/protocol")
async def download_my_assembly_protocol(
    assembly_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    """Authenticated download for the signed protocol PDF."""
    a = await svc.load_assembly_for_org(
        session,
        organization_id=current_user.organization_id,
        assembly_id=assembly_id,
    )
    if a is None or a.protocol_pdf_url is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Protocol not found")
    if current_user.role != UserRole.VERWALTER:
        if current_user.contact_id_impower is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Protocol not found")
        visible = await session.scalar(
            _visible_properties_stmt(current_user).where(Property.id == a.property_id)
        )
        if visible is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Protocol not found")
    path = Path(a.protocol_pdf_url)
    if not path.is_absolute():
        path = Path(settings.etv_protocol_dir) / path.name
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Protocol file missing")
    return FileResponse(
        str(path),
        media_type="application/pdf",
        filename=f"protokoll-{a.id}.pdf",
    )


# ----- Comments (Q&A thread) ------------------------------------------------


async def _check_assembly_visible(
    session: AsyncSession,
    *,
    current_user: User,
    assembly_id: uuid.UUID,
) -> EtvAssembly:
    """Loads + scope-checks an assembly for the comment routes.

    Verwalter can always read/write; other roles must be linked to
    the assembly's property via the standard owner-visibility
    check. Raises 404 to avoid existence-leaks.
    """
    a = await svc.load_assembly_for_org(
        session,
        organization_id=current_user.organization_id,
        assembly_id=assembly_id,
    )
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assembly not found")
    if current_user.role != UserRole.VERWALTER:
        if current_user.contact_id_impower is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assembly not found")
        visible = await session.scalar(
            _visible_properties_stmt(current_user).where(Property.id == a.property_id)
        )
        if visible is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assembly not found")
    return a


def _comment_to_response(c: EtvAssemblyComment, author: User) -> AssemblyCommentResponse:
    return AssemblyCommentResponse(
        id=c.id,
        assembly_id=c.assembly_id,
        author_user_id=c.author_user_id,
        author_label=author.email,
        author_role=author.role.value,
        body=c.body,
        created_at=c.created_at,
        edited_at=c.edited_at,
    )


@me_router.get(
    "/assemblies/{assembly_id}/comments",
    response_model=list[AssemblyCommentResponse],
)
async def list_assembly_comments(
    assembly_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AssemblyCommentResponse]:
    """Q&A thread under an assembly. Chronological."""
    await _check_assembly_visible(session, current_user=current_user, assembly_id=assembly_id)
    comments = (
        (
            await session.execute(
                select(EtvAssemblyComment)
                .where(EtvAssemblyComment.assembly_id == assembly_id)
                .order_by(EtvAssemblyComment.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    if not comments:
        return []
    author_ids = {c.author_user_id for c in comments}
    authors = (await session.execute(select(User).where(User.id.in_(author_ids)))).scalars().all()
    by_id = {a.id: a for a in authors}
    return [_comment_to_response(c, by_id[c.author_user_id]) for c in comments]


@me_router.post(
    "/assemblies/{assembly_id}/comments",
    response_model=AssemblyCommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_assembly_comment(
    assembly_id: uuid.UUID,
    req: CreateAssemblyCommentRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssemblyCommentResponse:
    """Post a new comment. Visible to everyone who can see the
    assembly (Verwalter + Eigentümer/Mieter/Beirat on the property)."""
    await _check_assembly_visible(session, current_user=current_user, assembly_id=assembly_id)
    c = EtvAssemblyComment(
        assembly_id=assembly_id,
        author_user_id=current_user.id,
        body=req.body,
    )
    session.add(c)
    await session.commit()
    await session.refresh(c)
    return _comment_to_response(c, current_user)


@me_router.patch(
    "/assembly-comments/{comment_id}",
    response_model=AssemblyCommentResponse,
)
async def edit_assembly_comment(
    comment_id: uuid.UUID,
    req: UpdateAssemblyCommentRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssemblyCommentResponse:
    """Author-only edit. Verwalter cannot edit other users' comments
    (moderation = hide/delete, not silent rewrite)."""
    c = await session.get(EtvAssemblyComment, comment_id)
    if c is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    if c.author_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the author can edit a comment",
        )
    await _check_assembly_visible(session, current_user=current_user, assembly_id=c.assembly_id)
    c.body = req.body
    c.edited_at = svc._now()
    await session.commit()
    await session.refresh(c)
    return _comment_to_response(c, current_user)


@me_router.delete(
    "/assembly-comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_assembly_comment(
    comment_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Author OR Verwalter can delete. Hard delete — moderation is
    out of scope for the Q&A v1; if abuse becomes a thing we'll
    layer in `is_hidden` like announcement comments."""
    c = await session.get(EtvAssemblyComment, comment_id)
    if c is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    is_author = c.author_user_id == current_user.id
    is_verwalter = current_user.role == UserRole.VERWALTER
    if not (is_author or is_verwalter):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the author or a Verwalter can delete a comment",
        )
    await _check_assembly_visible(session, current_user=current_user, assembly_id=c.assembly_id)
    await session.delete(c)
    await session.commit()


# =================================================================
# Admin / Verwalter side — full CRUD
# =================================================================


@admin_router.get(
    "/properties/{property_id}/assemblies",
    response_model=list[AssemblyResponse],
)
async def admin_list_property_assemblies(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AssemblyResponse]:
    """Verwalter view — includes ABGESAGT, ordered newest-first."""
    prop = await session.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.organization_id == current_user.organization_id,
            Property.deleted_at.is_(None),
        )
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")
    rows = await svc.list_assemblies_for_property(
        session,
        organization_id=current_user.organization_id,
        property_id=prop.id,
        include_cancelled=True,
    )
    props = await _props_by_id_for(session, rows)
    return [_assembly_to_list_response(a, props.get(a.property_id)) for a in rows]


@admin_router.get("/assemblies", response_model=list[AssemblyResponse])
async def admin_list_all_assemblies(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AssemblyResponse]:
    """Cross-property queue for the admin SPA's top-level overview."""
    rows = await svc.list_assemblies_for_org(session, organization_id=current_user.organization_id)
    props = await _props_by_id_for(session, rows)
    return [_assembly_to_list_response(a, props.get(a.property_id)) for a in rows]


@admin_router.post(
    "/properties/{property_id}/assemblies",
    response_model=AssemblyDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def admin_create_assembly(
    property_id: uuid.UUID,
    payload: CreateAssemblyRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssemblyDetailResponse:
    if payload.property_id != property_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="property_id in payload must match URL",
        )
    prop = await session.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.organization_id == current_user.organization_id,
            Property.deleted_at.is_(None),
        )
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    assembly = EtvAssembly(
        organization_id=current_user.organization_id,
        property_id=prop.id,
        title=payload.title,
        description=payload.description,
        scheduled_start=payload.scheduled_start,
        scheduled_end=payload.scheduled_end,
        location=payload.location,
        teams_meeting_url=payload.teams_meeting_url or None,
        created_by=current_user.id,
    )
    session.add(assembly)
    await session.flush()
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="etv_assembly_created",
            target_type="etv_assemblies",
            target_id=str(assembly.id),
            payload_json={
                "property_id": str(prop.id),
                "title": assembly.title,
                "scheduled_start": assembly.scheduled_start.isoformat(),
                "scheduled_end": assembly.scheduled_end.isoformat(),
                "location": assembly.location,
            },
        )
    )
    await session.commit()
    await session.refresh(assembly)
    return await _assembly_to_detail(session, assembly)


@admin_router.get("/assemblies/{assembly_id}", response_model=AssemblyDetailResponse)
async def admin_get_assembly(
    assembly_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssemblyDetailResponse:
    a = await svc.load_assembly_for_org(
        session,
        organization_id=current_user.organization_id,
        assembly_id=assembly_id,
    )
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assembly not found")
    return await _assembly_to_detail(session, a)


@admin_router.patch("/assemblies/{assembly_id}", response_model=AssemblyDetailResponse)
async def admin_update_assembly(
    assembly_id: uuid.UUID,
    payload: UpdateAssemblyRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssemblyDetailResponse:
    a = await svc.load_assembly_for_org(
        session,
        organization_id=current_user.organization_id,
        assembly_id=assembly_id,
    )
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assembly not found")
    diff: dict[str, object] = {}
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        old = getattr(a, field)
        if old != value:
            diff[field] = {
                "from": str(old) if old is not None else None,
                "to": str(value) if value is not None else None,
            }
            setattr(a, field, value)
    # Reject scheduled_end <= scheduled_start after the patch lands.
    if a.scheduled_end <= a.scheduled_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="scheduled_end must be after scheduled_start",
        )
    if diff:
        session.add(
            AuditLog(
                organization_id=current_user.organization_id,
                actor_user_id=current_user.id,
                action="etv_assembly_updated",
                target_type="etv_assemblies",
                target_id=str(a.id),
                payload_json={"diff": diff},
            )
        )
    await session.commit()
    await session.refresh(a)
    return await _assembly_to_detail(session, a)


@admin_router.delete("/assemblies/{assembly_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_soft_delete_assembly(
    assembly_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    a = await svc.load_assembly_for_org(
        session,
        organization_id=current_user.organization_id,
        assembly_id=assembly_id,
    )
    if a is None:
        return None
    a.deleted_at = svc._now()
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="etv_assembly_deleted",
            target_type="etv_assemblies",
            target_id=str(a.id),
            payload_json={"title": a.title},
        )
    )
    await session.commit()
    return None


# ---------- agenda items ----------


@admin_router.post(
    "/assemblies/{assembly_id}/agenda-items",
    response_model=AgendaItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def admin_add_agenda_item(
    assembly_id: uuid.UUID,
    payload: CreateAgendaItemRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgendaItemResponse:
    a = await svc.load_assembly_for_org(
        session,
        organization_id=current_user.organization_id,
        assembly_id=assembly_id,
    )
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assembly not found")
    item = EtvAgendaItem(
        assembly_id=a.id,
        position=payload.position,
        type=payload.type,
        title=payload.title,
        body=payload.body,
        beschluss_text=payload.beschluss_text,
        vote_required_quorum=payload.vote_required_quorum,
    )
    session.add(item)
    try:
        await session.flush()
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another agenda item already exists at this position",
        ) from exc
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="etv_agenda_item_added",
            target_type="etv_agenda_items",
            target_id=str(item.id),
            payload_json={
                "assembly_id": str(a.id),
                "position": item.position,
                "type": item.type.value,
                "title": item.title,
            },
        )
    )
    await session.commit()
    await session.refresh(item)
    return AgendaItemResponse(
        id=item.id,
        assembly_id=item.assembly_id,
        position=item.position,
        type=item.type,
        title=item.title,
        body=item.body,
        beschluss_text=item.beschluss_text,
        vote_yes=item.vote_yes,
        vote_no=item.vote_no,
        vote_abstain=item.vote_abstain,
        vote_required_quorum=item.vote_required_quorum,
        vote_result=item.vote_result,
        voting_basis=item.voting_basis,
        present_count=item.present_count,
        discussion=[],
    )


@admin_router.patch(
    "/agenda-items/{item_id}",
    response_model=AgendaItemResponse,
)
async def admin_update_agenda_item(
    item_id: uuid.UUID,
    payload: UpdateAgendaItemRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AgendaItemResponse:
    item = await session.scalar(
        select(EtvAgendaItem)
        .join(EtvAssembly, EtvAssembly.id == EtvAgendaItem.assembly_id)
        .where(
            EtvAgendaItem.id == item_id,
            EtvAssembly.organization_id == current_user.organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agenda item not found")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(item, field, value)
    # Enforce the same rule the create schema enforces: BESCHLUSS-only
    # fields must be empty on non-BESCHLUSS rows.
    if item.type != AgendaItemType.BESCHLUSS and (
        item.beschluss_text is not None or item.vote_required_quorum is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("beschluss_text + vote_required_quorum only allowed when type=BESCHLUSS"),
        )
    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another agenda item already exists at this position",
        ) from exc
    await session.refresh(item)
    return AgendaItemResponse(
        id=item.id,
        assembly_id=item.assembly_id,
        position=item.position,
        type=item.type,
        title=item.title,
        body=item.body,
        beschluss_text=item.beschluss_text,
        vote_yes=item.vote_yes,
        vote_no=item.vote_no,
        vote_abstain=item.vote_abstain,
        vote_required_quorum=item.vote_required_quorum,
        vote_result=item.vote_result,
        voting_basis=item.voting_basis,
        present_count=item.present_count,
        discussion=[],
    )


@admin_router.delete(
    "/agenda-items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_delete_agenda_item(
    item_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    item = await session.scalar(
        select(EtvAgendaItem)
        .join(EtvAssembly, EtvAssembly.id == EtvAgendaItem.assembly_id)
        .where(
            EtvAgendaItem.id == item_id,
            EtvAssembly.organization_id == current_user.organization_id,
        )
    )
    if item is None:
        return None
    await session.delete(item)
    await session.commit()
    return None


# ---------- discussion entries ----------


@admin_router.post(
    "/agenda-items/{item_id}/discussion",
    response_model=DiscussionEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def admin_add_discussion_entry(
    item_id: uuid.UUID,
    payload: CreateDiscussionEntryRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DiscussionEntryResponse:
    item = await session.scalar(
        select(EtvAgendaItem)
        .join(EtvAssembly, EtvAssembly.id == EtvAgendaItem.assembly_id)
        .where(
            EtvAgendaItem.id == item_id,
            EtvAssembly.organization_id == current_user.organization_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agenda item not found")
    entry = EtvDiscussionEntry(
        agenda_item_id=item.id,
        position=payload.position,
        speaker_label=payload.speaker_label,
        content=payload.content,
    )
    session.add(entry)
    try:
        await session.flush()
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another discussion entry already exists at this position",
        ) from exc
    await session.commit()
    await session.refresh(entry)
    return DiscussionEntryResponse.model_validate(entry)


@admin_router.delete(
    "/discussion/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_delete_discussion_entry(
    entry_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    entry = await session.scalar(
        select(EtvDiscussionEntry)
        .join(EtvAgendaItem, EtvAgendaItem.id == EtvDiscussionEntry.agenda_item_id)
        .join(EtvAssembly, EtvAssembly.id == EtvAgendaItem.assembly_id)
        .where(
            EtvDiscussionEntry.id == entry_id,
            EtvAssembly.organization_id == current_user.organization_id,
        )
    )
    if entry is None:
        return None
    await session.delete(entry)
    await session.commit()
    return None


# ---------- protocol upload ----------


@admin_router.post(
    "/assemblies/{assembly_id}/protocol",
    response_model=ProtocolUploadResponse,
)
async def admin_upload_protocol(
    assembly_id: uuid.UUID,
    file: UploadFile,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProtocolUploadResponse:
    """Upload the signed protocol PDF. Replacing an existing protocol
    is permitted (the new file overwrites the URL + bumps the
    uploaded_at timestamp). The old PDF on disk is intentionally not
    deleted — we keep both as evidence trail; later GC if needed."""
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF uploads accepted",
        )
    a = await svc.load_assembly_for_org(
        session,
        organization_id=current_user.organization_id,
        assembly_id=assembly_id,
    )
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assembly not found")

    upload_root = Path(settings.etv_protocol_dir)
    upload_root.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 — file IO at startup of a one-off upload, low-volume route
    target = upload_root / f"{a.id}.pdf"
    # Stream copy to avoid pulling the entire PDF into memory.
    # Enforce the configured size cap as we go — anything over kills
    # the partial file + 413s.
    written = 0
    cap = settings.etv_protocol_max_bytes
    with target.open("wb") as out:
        while chunk := await file.read(64 * 1024):
            written += len(chunk)
            if written > cap:
                out.close()
                target.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Protocol exceeds {cap // (1024 * 1024)} MB cap",
                )
            out.write(chunk)
    # Store relative filename so the same row keeps working if the
    # upload root moves (local → Hetzner OS bucket).
    a.protocol_pdf_url = target.name
    a.protocol_uploaded_at = svc._now()
    # Re-uploading the protocol clears the prior extraction stamp so
    # the badge reappears for a fresh review cycle. Verified rows
    # keep verified_at — the service-level guard short-circuits the
    # next pass for them.
    a.protocol_extracted_at = None
    a.protocol_extracted_raw = None
    a.protocol_extracted_source_document_id = None
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="etv_protocol_uploaded",
            target_type="etv_assemblies",
            target_id=str(a.id),
            payload_json={
                "filename": file.filename,
                "protocol_pdf_url": a.protocol_pdf_url,
            },
        )
    )
    await session.commit()
    await session.refresh(a)

    extraction_enqueued = False
    try:
        from app.workers.tasks import extract_etv_protocol

        extract_etv_protocol.delay(str(a.id))
        extraction_enqueued = True
    except Exception:
        logger.exception("failed to enqueue protocol extraction for assembly %s", a.id)

    return ProtocolUploadResponse(
        assembly_id=a.id,
        protocol_pdf_url=a.protocol_pdf_url,
        protocol_uploaded_at=a.protocol_uploaded_at,
        extraction_enqueued=extraction_enqueued,
    )


# ----- Verify (admin sign-off on auto-extracted data) -----------------------


@admin_router.post(
    "/assemblies/{assembly_id}/verify",
    response_model=AssemblyDetailResponse,
)
async def admin_verify_assembly(
    assembly_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    kind: Literal["invitation", "protocol"] = "invitation",
) -> AssemblyDetailResponse:
    """Verwalter sign-off on auto-extracted data. Two-stage:

      kind=invitation (default, backward compat): sets `verified_at` +
        `verified_by_user_id`. Locks the invitation-derived fields
        (meeting date, location, agenda titles) against future
        re-extractions. Does NOT block protocol extraction.
      kind=protocol: sets `protocol_verified_at` +
        `protocol_verified_by_user_id`. Locks the protocol-derived
        fields (vote tallies, discussion, actual_start/end).

    Idempotent: re-verifying a row just bumps the timestamp.
    """
    a = await svc.load_assembly_for_org(
        session,
        organization_id=current_user.organization_id,
        assembly_id=assembly_id,
    )
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assembly not found")
    if kind == "invitation":
        a.verified_at = svc._now()
        a.verified_by_user_id = current_user.id
    else:
        a.protocol_verified_at = svc._now()
        a.protocol_verified_by_user_id = current_user.id
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action=f"etv_assembly_verified_{kind}",
            target_type="etv_assemblies",
            target_id=str(a.id),
            payload_json={},
        )
    )
    await session.commit()
    await session.refresh(a)
    return await _assembly_to_detail(session, a)


# ----- Invitation PDF -------------------------------------------------------


@me_router.get("/assemblies/{assembly_id}/invitation")
async def download_my_assembly_invitation(
    assembly_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    """Auth-gated download for the Einladung PDF.

    Same scope check as the protocol download — Verwalter sees all
    org assemblies; owner only those tied to a property they have a
    contract on.
    """
    a = await svc.load_assembly_for_org(
        session,
        organization_id=current_user.organization_id,
        assembly_id=assembly_id,
    )
    if a is None or a.invitation_pdf_url is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    if current_user.role != UserRole.VERWALTER:
        if current_user.contact_id_impower is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found"
            )
        visible = await session.scalar(
            _visible_properties_stmt(current_user).where(Property.id == a.property_id)
        )
        if visible is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found"
            )
    path = Path(a.invitation_pdf_url)
    if not path.is_absolute():
        path = Path(settings.etv_invitation_dir) / path.name
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation file missing")
    return FileResponse(
        str(path),
        media_type="application/pdf",
        filename=f"einladung-{a.id}.pdf",
    )


@admin_router.post(
    "/assemblies/{assembly_id}/invitation",
    response_model=InvitationUploadResponse,
)
async def admin_upload_invitation(
    assembly_id: uuid.UUID,
    file: UploadFile,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> InvitationUploadResponse:
    """Upload the Einladung PDF + trigger LLM extraction.

    The new PDF overwrites the previous one on disk. The associated
    extraction task is enqueued on the celery queue and runs against
    the freshly-uploaded bytes; the SPA polls
    `/admin/assemblies/{id}` to see when `auto_extracted_at` flips.
    """
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF uploads accepted",
        )
    a = await svc.load_assembly_for_org(
        session,
        organization_id=current_user.organization_id,
        assembly_id=assembly_id,
    )
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assembly not found")

    upload_root = Path(settings.etv_invitation_dir)
    upload_root.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 — one-off route
    target = upload_root / f"{a.id}.pdf"
    written = 0
    cap = settings.etv_invitation_max_bytes
    with target.open("wb") as out:
        while chunk := await file.read(64 * 1024):
            written += len(chunk)
            if written > cap:
                out.close()
                target.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Invitation exceeds {cap // (1024 * 1024)} MB cap",
                )
            out.write(chunk)
    a.invitation_pdf_url = target.name
    a.invitation_uploaded_at = svc._now()
    # Re-uploading clears the prior extraction stamp so the SPA badge
    # ("KI-extrahiert · bitte prüfen") reappears until the new pass
    # lands. Verified rows keep their verified_at — the next
    # extraction will see verified_at and skip per the
    # service-level idempotency guard.
    a.auto_extracted_at = None
    a.auto_extracted_raw = None
    a.auto_extracted_source_document_id = None
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="etv_invitation_uploaded",
            target_type="etv_assemblies",
            target_id=str(a.id),
            payload_json={
                "filename": file.filename,
                "invitation_pdf_url": a.invitation_pdf_url,
            },
        )
    )
    await session.commit()
    await session.refresh(a)

    # Enqueue extraction *after* commit so the Celery worker sees the
    # freshly-persisted invitation_pdf_url. Failure here doesn't roll
    # back the upload — the Verwalter can re-trigger from the SPA.
    extraction_enqueued = False
    try:
        from app.workers.tasks import extract_etv_metadata

        extract_etv_metadata.delay(str(a.id))
        extraction_enqueued = True
    except Exception:
        logger.exception("failed to enqueue extraction for assembly %s", a.id)

    return InvitationUploadResponse(
        assembly_id=a.id,
        invitation_pdf_url=a.invitation_pdf_url,
        invitation_uploaded_at=a.invitation_uploaded_at,
        extraction_enqueued=extraction_enqueued,
    )


@admin_router.delete(
    "/assemblies/{assembly_id}/invitation",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_delete_invitation(
    assembly_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Remove the invitation file + clear the row pointers.

    Auto-extracted data stays — the Verwalter may want to keep the
    parsed agenda even if they pulled the source PDF for re-upload.
    """
    a = await svc.load_assembly_for_org(
        session,
        organization_id=current_user.organization_id,
        assembly_id=assembly_id,
    )
    if a is None or a.invitation_pdf_url is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    path = Path(a.invitation_pdf_url)
    if not path.is_absolute():
        path = Path(settings.etv_invitation_dir) / path.name
    path.unlink(missing_ok=True)
    a.invitation_pdf_url = None
    a.invitation_uploaded_at = None
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="etv_invitation_deleted",
            target_type="etv_assemblies",
            target_id=str(a.id),
            payload_json={},
        )
    )
    await session.commit()
