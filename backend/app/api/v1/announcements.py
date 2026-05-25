"""Announcement (Mitteilung) endpoints — admin (/admin) + owner (/me).

Both routers live in this file because they share helpers
(`_to_response`, the attachment download resolver). They mount under
different prefixes via main.py. Heavy lifecycle logic lives in
`app/services/announcements.py` — handlers here only do org-scope +
audience checks, schema marshalling, and audit-log writes.

Comment moderation has its own flat URL under `/admin/announcement-comments`
so admins can hide / unhide without re-routing through the parent
announcement detail load.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.me import _visible_properties_stmt
from app.auth.dependencies import get_current_user, require_role
from app.config import Settings, get_settings
from app.db import get_session
from app.integrations.email.announcements import render_comment_notification_email
from app.integrations.email.client import EmailClient, EmailError, get_email_client
from app.integrations.storage.announcements import (
    AnnouncementAttachmentStorageError,
    attachment_path,
    write_attachment,
)
from app.integrations.storage.announcements import (
    delete_attachment as delete_attachment_file,
)
from app.models import (
    Announcement,
    AnnouncementAttachment,
    AnnouncementComment,
    AuditLog,
    Property,
    SendAttemptStatus,
    Unit,
    User,
    UserRole,
)
from app.schemas.announcement import (
    AnnouncementAttachmentResponse,
    AnnouncementCommentCreateRequest,
    AnnouncementCommentEditRequest,
    AnnouncementCommentModerationRequest,
    AnnouncementCommentResponse,
    AnnouncementCommentVersionResponse,
    AnnouncementCreateRequest,
    AnnouncementDetailResponse,
    AnnouncementResendSummary,
    AnnouncementResponse,
    AnnouncementSendAttemptResponse,
    AnnouncementUpdateRequest,
    RecipientPreviewItem,
    RecipientPreviewResponse,
)
from app.services import announcements as svc

logger = logging.getLogger(__name__)

me_router = APIRouter(prefix="/me", tags=["announcements"])
admin_router = APIRouter(prefix="/admin", tags=["announcements"])

_verwalter_only = require_role(UserRole.VERWALTER)


# --- helpers ---------------------------------------------------------------


async def _load_property_for_admin(
    session: AsyncSession, *, organization_id: uuid.UUID, property_id: uuid.UUID
) -> Property:
    """Verwalter scope: property must belong to caller's org + not be
    deleted. Returns the row or raises 404."""
    prop: Property | None = await session.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.organization_id == organization_id,
            Property.deleted_at.is_(None),
        )
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")
    return prop


async def _load_property_for_owner(
    session: AsyncSession, *, user: User, property_id: uuid.UUID
) -> Property:
    """Portal scope: property must be in the user's visible set (via
    contact → contract). Returns the row or raises 404."""
    stmt = _visible_properties_stmt(user).where(Property.id == property_id)
    prop: Property | None = await session.scalar(stmt)
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")
    return prop


async def _validate_units_for_property(
    session: AsyncSession, *, property_id: uuid.UUID, unit_ids: list[uuid.UUID]
) -> None:
    """Reject unit_ids that don't belong to the announcement's property.

    The fan-out join would silently return zero recipients if a unit
    on a different property snuck in, but the audit trail would
    capture nonsense. Surface as 400 at request time instead.
    """
    if not unit_ids:
        return
    found = (
        await session.scalars(
            select(Unit.id).where(
                Unit.id.in_(unit_ids),
                Unit.property_id == property_id,
            )
        )
    ).all()
    found_set = set(found)
    invalid = [uid for uid in unit_ids if uid not in found_set]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"{len(invalid)} unit(s) do not belong to this property"),
        )


async def _enrich_response(
    session: AsyncSession,
    announcement: Announcement,
    *,
    attachment_count: int | None = None,
    comment_count: int | None = None,
) -> AnnouncementResponse:
    """Populate the denormalised fields on an AnnouncementResponse so
    list / detail handlers don't all repeat the same joins.

    `attachment_count` / `comment_count` can be precomputed by the
    caller (e.g. via a batch COUNT query); when omitted, we run a
    per-row SELECT COUNT. Fine for detail handlers; list handlers
    should batch.
    """
    base = AnnouncementResponse.model_validate(announcement)
    base.is_edited = svc.is_edited_post_publish(announcement)

    prop = await session.scalar(select(Property).where(Property.id == announcement.property_id))
    base.property_name = prop.name if prop else None

    creator = await session.scalar(select(User).where(User.id == announcement.created_by_user_id))
    base.creator_email = creator.email if creator else None

    if attachment_count is None:
        attachment_count = (
            await session.scalar(
                select(func.count(AnnouncementAttachment.id)).where(
                    AnnouncementAttachment.announcement_id == announcement.id
                )
            )
        ) or 0
    base.attachment_count = int(attachment_count)

    if comment_count is None:
        comment_count = (
            await session.scalar(
                select(func.count(AnnouncementComment.id)).where(
                    AnnouncementComment.announcement_id == announcement.id,
                    AnnouncementComment.is_hidden.is_(False),
                )
            )
        ) or 0
    base.comment_count = int(comment_count)
    base.unit_ids = await svc.list_targeted_unit_ids(session, announcement.id)
    base.excluded_user_ids = list(announcement.excluded_user_ids or [])
    base.extra_emails = list(announcement.extra_emails or [])

    return base


async def _enrich_summaries(
    session: AsyncSession, rows: list[Announcement]
) -> list[AnnouncementResponse]:
    """Batch-resolve property name + creator email + counts for a list.

    Three batch queries (properties, users, counts) cover any size of
    result. We use this on the list endpoints to avoid the N+1 trap
    the per-row `_enrich_response` would create.
    """
    if not rows:
        return []
    prop_ids = {r.property_id for r in rows}
    user_ids = {r.created_by_user_id for r in rows}
    ann_ids = [r.id for r in rows]

    props = {
        p.id: p
        for p in (await session.scalars(select(Property).where(Property.id.in_(prop_ids)))).all()
    }
    users = {
        u.id: u for u in (await session.scalars(select(User).where(User.id.in_(user_ids)))).all()
    }
    att_counts: dict[uuid.UUID, int] = {
        row[0]: int(row[1])
        for row in (
            await session.execute(
                select(
                    AnnouncementAttachment.announcement_id,
                    func.count(AnnouncementAttachment.id),
                )
                .where(AnnouncementAttachment.announcement_id.in_(ann_ids))
                .group_by(AnnouncementAttachment.announcement_id)
            )
        ).all()
    }
    com_counts: dict[uuid.UUID, int] = {
        row[0]: int(row[1])
        for row in (
            await session.execute(
                select(
                    AnnouncementComment.announcement_id,
                    func.count(AnnouncementComment.id),
                )
                .where(
                    AnnouncementComment.announcement_id.in_(ann_ids),
                    AnnouncementComment.is_hidden.is_(False),
                )
                .group_by(AnnouncementComment.announcement_id)
            )
        ).all()
    }

    # Batch unit_ids per announcement so the SPA list view can render
    # "n Einheiten" without a follow-up request.
    from app.models import AnnouncementUnit as _AnnouncementUnit

    unit_rows = (
        await session.execute(
            select(
                _AnnouncementUnit.announcement_id,
                _AnnouncementUnit.unit_id,
            ).where(_AnnouncementUnit.announcement_id.in_(ann_ids))
        )
    ).all()
    units_by_ann: dict[uuid.UUID, list[uuid.UUID]] = {}
    for ann_id, unit_id in unit_rows:
        units_by_ann.setdefault(ann_id, []).append(unit_id)

    out: list[AnnouncementResponse] = []
    for r in rows:
        resp = AnnouncementResponse.model_validate(r)
        resp.is_edited = svc.is_edited_post_publish(r)
        p = props.get(r.property_id)
        resp.property_name = p.name if p else None
        u = users.get(r.created_by_user_id)
        resp.creator_email = u.email if u else None
        resp.attachment_count = att_counts.get(r.id, 0)
        resp.comment_count = com_counts.get(r.id, 0)
        resp.unit_ids = units_by_ann.get(r.id, [])
        resp.excluded_user_ids = list(r.excluded_user_ids or [])
        resp.extra_emails = list(r.extra_emails or [])
        out.append(resp)
    return out


def _comment_to_response(
    comment: AnnouncementComment, *, author_email: str | None
) -> AnnouncementCommentResponse:
    resp = AnnouncementCommentResponse.model_validate(comment)
    resp.author_email = author_email
    return resp


async def _comments_with_emails(
    session: AsyncSession, comments: list[AnnouncementComment]
) -> list[AnnouncementCommentResponse]:
    if not comments:
        return []
    author_ids = {c.author_user_id for c in comments}
    emails = {
        u.id: u.email
        for u in (await session.scalars(select(User).where(User.id.in_(author_ids)))).all()
    }
    return [_comment_to_response(c, author_email=emails.get(c.author_user_id)) for c in comments]


# --- admin: announcements lifecycle ---------------------------------------


@admin_router.post(
    "/properties/{property_id}/announcements",
    response_model=AnnouncementResponse,
    status_code=status.HTTP_201_CREATED,
)
async def admin_create_announcement(
    property_id: uuid.UUID,
    payload: AnnouncementCreateRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AnnouncementResponse:
    """Compose a new Mitteilung. Notifications fan out 10 minutes after
    this call (each subsequent edit resets the timer)."""
    prop = await _load_property_for_admin(
        session,
        organization_id=current_user.organization_id,
        property_id=property_id,
    )
    # Validate any per-unit narrowing before we touch the row.
    await _validate_units_for_property(session, property_id=prop.id, unit_ids=payload.unit_ids)
    announcement = svc.create_announcement(
        session,
        organization_id=current_user.organization_id,
        property_id=prop.id,
        author=current_user,
        payload=payload,
    )
    await session.flush()  # populate id before audit log writes target_id
    if payload.unit_ids:
        await svc.replace_targeted_units(
            session, announcement=announcement, unit_ids=payload.unit_ids
        )
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="announcement_created",
            target_type="announcements",
            target_id=str(announcement.id),
            payload_json={
                "property_id": str(prop.id),
                "title": announcement.title,
                "audience_eigentuemer": announcement.audience_eigentuemer,
                "audience_mieter": announcement.audience_mieter,
                "audience_beirat": announcement.audience_beirat,
                "unit_ids": [str(u) for u in payload.unit_ids],
                "scheduled_publish_at": announcement.scheduled_publish_at.isoformat(),
            },
        )
    )
    await session.commit()
    await session.refresh(announcement)
    return await _enrich_response(session, announcement, attachment_count=0, comment_count=0)


@admin_router.get(
    "/properties/{property_id}/announcements",
    response_model=list[AnnouncementResponse],
)
async def admin_list_announcements(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[
        Literal["all", "scheduled", "published"], Query(alias="status")
    ] = "all",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AnnouncementResponse]:
    """Admin queue. `status=scheduled` filters to unpublished;
    `status=published` to already-sent; `status=all` (default) returns
    both. Soft-deleted rows excluded in all modes."""
    await _load_property_for_admin(
        session,
        organization_id=current_user.organization_id,
        property_id=property_id,
    )
    rows, _ = await svc.list_for_property_admin(
        session,
        organization_id=current_user.organization_id,
        property_id=property_id,
        limit=limit,
        offset=offset,
    )
    if status_filter == "scheduled":
        rows = [r for r in rows if r.notification_sent_at is None]
    elif status_filter == "published":
        rows = [r for r in rows if r.notification_sent_at is not None]
    return await _enrich_summaries(session, rows)


@admin_router.get(
    "/announcements",
    response_model=list[AnnouncementResponse],
)
async def admin_list_all_announcements(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[
        Literal["all", "scheduled", "published"], Query(alias="status")
    ] = "all",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AnnouncementResponse]:
    """Cross-property org-wide queue. Same filter semantics as the
    per-property endpoint; rows ordered by `scheduled_publish_at`
    descending so the most recent / next-due Mitteilung lands first."""
    rows, _ = await svc.list_for_org_admin(
        session,
        organization_id=current_user.organization_id,
        limit=limit,
        offset=offset,
    )
    if status_filter == "scheduled":
        rows = [r for r in rows if r.notification_sent_at is None]
    elif status_filter == "published":
        rows = [r for r in rows if r.notification_sent_at is not None]
    return await _enrich_summaries(session, rows)


@admin_router.get(
    "/announcements/{announcement_id}",
    response_model=AnnouncementDetailResponse,
)
async def admin_get_announcement(
    announcement_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AnnouncementDetailResponse:
    """Full detail incl. attachments + comments (hidden comments
    visible to admin)."""
    announcement = await svc.get_admin(
        session,
        announcement_id=announcement_id,
        organization_id=current_user.organization_id,
    )
    if announcement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found",
        )
    summary = await _enrich_response(session, announcement)
    attachments = await svc.list_attachments(session, announcement.id)
    comments = await svc.list_comments(session, announcement.id, include_hidden=True)
    return AnnouncementDetailResponse(
        **summary.model_dump(),
        attachments=[AnnouncementAttachmentResponse.model_validate(a) for a in attachments],
        comments=await _comments_with_emails(session, comments),
    )


@admin_router.patch("/announcements/{announcement_id}", response_model=AnnouncementResponse)
async def admin_update_announcement(
    announcement_id: uuid.UUID,
    payload: AnnouncementUpdateRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AnnouncementResponse:
    """Edit title / body / audience.

    While unpublished this resets `scheduled_publish_at = now() + 10 min`
    — every save buys another review window. Post-publish edits stick
    but the timer is frozen and the portal shows a "bearbeitet am"
    indicator.
    """
    announcement = await svc.get_admin(
        session,
        announcement_id=announcement_id,
        organization_id=current_user.organization_id,
    )
    if announcement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found",
        )
    try:
        svc.apply_update(announcement, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if payload.unit_ids is not None:
        # `None` = leave existing rows alone; explicit list (including
        # empty []) replaces the entire set. Validate every supplied
        # unit belongs to the announcement's property before swapping.
        await _validate_units_for_property(
            session,
            property_id=announcement.property_id,
            unit_ids=payload.unit_ids,
        )
        await svc.replace_targeted_units(
            session, announcement=announcement, unit_ids=payload.unit_ids
        )
    # Recipient-editor overrides — same partial-PATCH semantics as
    # unit_ids: None = leave alone, list = full replace.
    if payload.excluded_user_ids is not None or payload.extra_emails is not None:
        svc.apply_recipient_overrides(
            announcement,
            excluded_user_ids=payload.excluded_user_ids,
            extra_emails=payload.extra_emails,
        )
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="announcement_updated",
            target_type="announcements",
            target_id=str(announcement.id),
            payload_json={
                "patch": payload.model_dump(exclude_none=True),
                "scheduled_publish_at": announcement.scheduled_publish_at.isoformat(),
                "is_published": svc.is_published(announcement),
            },
        )
    )
    await session.commit()
    await session.refresh(announcement)
    return await _enrich_response(session, announcement)


@admin_router.post(
    "/announcements/{announcement_id}/publish-now",
    response_model=AnnouncementResponse,
)
async def admin_publish_now(
    announcement_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AnnouncementResponse:
    """Collapse the editorial-buffer countdown to zero. The next Celery
    beat tick (1-min cadence) fans out. No-op when already published."""
    announcement = await svc.get_admin(
        session,
        announcement_id=announcement_id,
        organization_id=current_user.organization_id,
    )
    if announcement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found",
        )
    if svc.is_published(announcement):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Announcement already published",
        )
    svc.publish_now(announcement)
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="announcement_publish_now",
            target_type="announcements",
            target_id=str(announcement.id),
            payload_json={
                "scheduled_publish_at": announcement.scheduled_publish_at.isoformat(),
            },
        )
    )
    await session.commit()
    await session.refresh(announcement)
    return await _enrich_response(session, announcement)


@admin_router.delete(
    "/announcements/{announcement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_delete_announcement(
    announcement_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Soft-delete. Pre-publish deletes also prevent the fan-out
    (the row drops out of the publish-due partial index)."""
    announcement = await svc.get_admin(
        session,
        announcement_id=announcement_id,
        organization_id=current_user.organization_id,
    )
    if announcement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found",
        )
    svc.soft_delete(announcement)
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="announcement_deleted",
            target_type="announcements",
            target_id=str(announcement.id),
            payload_json={
                "was_published": svc.is_published(announcement),
            },
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- admin: attachments ----------------------------------------------------


@admin_router.post(
    "/announcements/{announcement_id}/attachments",
    response_model=AnnouncementAttachmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def admin_upload_attachment(
    announcement_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: UploadFile,
) -> AnnouncementAttachmentResponse:
    """Attach a file to the announcement. Multipart upload; size cap
    enforced via `announcement_attachment_max_bytes`."""
    announcement = await svc.get_admin(
        session,
        announcement_id=announcement_id,
        organization_id=current_user.organization_id,
    )
    if announcement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found",
        )

    data = await file.read()
    if len(data) > settings.announcement_attachment_max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Datei zu groß "
            f"(max {settings.announcement_attachment_max_bytes // (1024 * 1024)} MB)",
        )

    attachment = AnnouncementAttachment(
        announcement_id=announcement.id,
        filename=file.filename or "attachment",
        mime_type=file.content_type,
        size_bytes=len(data),
        storage_url="local-disk:",  # final suffix stamped after write
        uploaded_by_user_id=current_user.id,
    )
    session.add(attachment)
    await session.flush()  # populate attachment.id for the file path

    try:
        _, suffix = write_attachment(attachment.id, attachment.filename, data)
    except AnnouncementAttachmentStorageError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ungültige Datei: {exc}",
        ) from exc

    attachment.storage_url = f"local-disk:{suffix}"
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="announcement_attachment_uploaded",
            target_type="announcement_attachments",
            target_id=str(attachment.id),
            payload_json={
                "announcement_id": str(announcement.id),
                "filename": attachment.filename,
                "size_bytes": attachment.size_bytes,
                "mime_type": attachment.mime_type,
            },
        )
    )
    await session.commit()
    await session.refresh(attachment)
    return AnnouncementAttachmentResponse.model_validate(attachment)


@admin_router.delete(
    "/announcements/{announcement_id}/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_delete_attachment(
    announcement_id: uuid.UUID,
    attachment_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    announcement = await svc.get_admin(
        session,
        announcement_id=announcement_id,
        organization_id=current_user.organization_id,
    )
    if announcement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found",
        )
    attachment = await session.scalar(
        select(AnnouncementAttachment).where(
            AnnouncementAttachment.id == attachment_id,
            AnnouncementAttachment.announcement_id == announcement.id,
        )
    )
    if attachment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found",
        )

    # Best-effort file cleanup. If the file isn't on disk (test
    # environment, half-written upload) we still drop the DB row.
    if attachment.storage_url.startswith("local-disk:"):
        suffix = attachment.storage_url[len("local-disk:") :]
        try:
            delete_attachment_file(attachment.id, suffix)
        except OSError:
            logger.warning(
                "Could not unlink announcement attachment %s — DB row will be removed anyway",
                attachment.id,
            )

    await session.delete(attachment)
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="announcement_attachment_deleted",
            target_type="announcement_attachments",
            target_id=str(attachment_id),
            payload_json={"announcement_id": str(announcement.id)},
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _serve_attachment(attachment: AnnouncementAttachment) -> FileResponse:
    """Shared file-streaming helper for the admin + owner download
    endpoints. 404s when the file isn't on disk (admin manually pruned
    the storage dir, etc.)."""
    if not attachment.storage_url.startswith("local-disk:"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Datei ist nicht lokal hinterlegt.",
        )
    suffix = attachment.storage_url[len("local-disk:") :]
    path = attachment_path(attachment.id, suffix)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Datei wurde nicht gefunden.",
        )
    return FileResponse(
        path,
        media_type=attachment.mime_type or "application/octet-stream",
        filename=attachment.filename,
    )


@admin_router.get(
    "/announcements/{announcement_id}/recipient-preview",
    response_model=RecipientPreviewResponse,
)
async def admin_recipient_preview(
    announcement_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RecipientPreviewResponse:
    """Render the recipient editor: the auto-resolved set (with the
    admin's excludes flagged) + every extra email + the final list
    that the next send would actually fan out to."""
    announcement = await svc.get_admin(
        session,
        announcement_id=announcement_id,
        organization_id=current_user.organization_id,
    )
    if announcement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found",
        )
    items, active = await svc.build_recipient_preview(session, announcement)
    return RecipientPreviewResponse(
        items=[RecipientPreviewItem(**item) for item in items],
        active_emails=active,
    )


@admin_router.get(
    "/announcements/{announcement_id}/send-attempts",
    response_model=list[AnnouncementSendAttemptResponse],
)
async def admin_list_send_attempts(
    announcement_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AnnouncementSendAttemptResponse]:
    """Per-recipient send log for an announcement. Newest first."""
    announcement = await svc.get_admin(
        session,
        announcement_id=announcement_id,
        organization_id=current_user.organization_id,
    )
    if announcement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found",
        )
    rows = await svc.list_send_attempts(session, announcement.id)
    return [AnnouncementSendAttemptResponse.model_validate(r) for r in rows]


@admin_router.post(
    "/announcements/{announcement_id}/resend",
    response_model=AnnouncementResendSummary,
)
async def admin_resend(
    announcement_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
) -> AnnouncementResendSummary:
    """Send the Mitteilung again to the *current* active recipient set.

    Replaces the v1.1 "Erneut senden für fehlgeschlagene" semantics
    (which only retried FAILED rows). v1.2 sends to every recipient
    the active set currently resolves to — auto users not in
    excluded_user_ids, plus extra_emails. Both prior-successful and
    prior-failed addresses get a fresh attempt row. Admin's mental
    model is "the audience just changed (excluded/added/edited body),
    redo the fan-out".
    """
    announcement = await svc.get_admin(
        session,
        announcement_id=announcement_id,
        organization_id=current_user.organization_id,
    )
    if announcement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found",
        )

    recipient_pairs = await svc.resolve_active_recipients(session, announcement)
    if not recipient_pairs:
        return AnnouncementResendSummary(
            attempted=0, succeeded=0, failed=0, error_message_examples=[]
        )

    # Rebuild the email body from current state so any post-publish
    # admin edits (title / body / audience / attachments) land in the
    # resend — that's the whole point of an explicit "send again".
    prop = await session.scalar(select(Property).where(Property.id == announcement.property_id))
    property_name = prop.name if prop else "—"
    attachments = await svc.list_attachments(session, announcement.id)
    from app.integrations.email.announcements import render_publish_email
    from app.workers.tasks import _read_attachments_for_send

    resend_attachments = _read_attachments_for_send(attachments)
    subject, html, text = render_publish_email(
        announcement_id=str(announcement.id),
        title=announcement.title,
        body=announcement.body,
        property_name=property_name,
        published_at=announcement.notification_sent_at or announcement.updated_at,
        attachment_count=len(resend_attachments),
    )

    succeeded = 0
    failed = 0
    errors: list[str] = []
    for recipient_user, recipient_email in recipient_pairs:
        try:
            await email_client.send(
                to=[recipient_email],
                subject=subject,
                html=html,
                text=text,
                attachments=resend_attachments or None,
            )
            svc.record_send_attempt(
                session,
                announcement=announcement,
                recipient_user=recipient_user,
                recipient_email=recipient_email,
                status=SendAttemptStatus.SUCCESS,
            )
            succeeded += 1
        except EmailError as exc:
            failed += 1
            svc.record_send_attempt(
                session,
                announcement=announcement,
                recipient_user=recipient_user,
                recipient_email=recipient_email,
                status=SendAttemptStatus.FAILED,
                error_message=str(exc),
            )
            errors.append(str(exc))

    session.add(
        AuditLog(
            organization_id=announcement.organization_id,
            actor_user_id=current_user.id,
            action="announcement_resend",
            target_type="announcements",
            target_id=str(announcement.id),
            payload_json={
                "attempted": len(recipient_pairs),
                "succeeded": succeeded,
                "failed": failed,
            },
        )
    )
    await session.commit()

    # De-dupe error strings, surface up to 3 to keep the SPA toast tidy.
    distinct_errors: list[str] = []
    seen: set[str] = set()
    for e in errors:
        if e and e not in seen:
            distinct_errors.append(e[:200])
            seen.add(e)
        if len(distinct_errors) >= 3:
            break

    return AnnouncementResendSummary(
        attempted=len(recipient_pairs),
        succeeded=succeeded,
        failed=failed,
        error_message_examples=distinct_errors,
    )


@admin_router.get("/announcements/{announcement_id}/attachments/{attachment_id}/download")
async def admin_download_attachment(
    announcement_id: uuid.UUID,
    attachment_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    announcement = await svc.get_admin(
        session,
        announcement_id=announcement_id,
        organization_id=current_user.organization_id,
    )
    if announcement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found",
        )
    attachment = await session.scalar(
        select(AnnouncementAttachment).where(
            AnnouncementAttachment.id == attachment_id,
            AnnouncementAttachment.announcement_id == announcement.id,
        )
    )
    if attachment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found",
        )
    return _serve_attachment(attachment)


# --- admin: comment moderation --------------------------------------------


@admin_router.patch(
    "/announcement-comments/{comment_id}",
    response_model=AnnouncementCommentResponse,
)
async def admin_moderate_comment(
    comment_id: uuid.UUID,
    payload: AnnouncementCommentModerationRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AnnouncementCommentResponse:
    """Hide / unhide a user-authored comment.

    Looks up the comment's announcement to verify the admin's org owns
    it before mutating — flat URL doesn't carry that scope hint.
    """
    row = await session.scalar(
        select(AnnouncementComment, Announcement)
        .join(
            Announcement,
            Announcement.id == AnnouncementComment.announcement_id,
        )
        .where(
            AnnouncementComment.id == comment_id,
            Announcement.organization_id == current_user.organization_id,
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment not found",
        )
    # session.scalar with a row tuple returns the first element, but
    # we want both; re-fetch explicitly to keep types tidy.
    comment = await session.scalar(
        select(AnnouncementComment).where(AnnouncementComment.id == comment_id)
    )
    if comment is None:
        # Race-condition guard — caught implicitly above; reassert
        # for the type checker.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")

    svc.set_comment_hidden(
        comment=comment,
        is_hidden=payload.is_hidden,
        moderator=current_user,
        reason=payload.hidden_reason,
    )
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action=(
                "announcement_comment_hidden"
                if payload.is_hidden
                else "announcement_comment_unhidden"
            ),
            target_type="announcement_comments",
            target_id=str(comment.id),
            payload_json={
                "announcement_id": str(comment.announcement_id),
                "reason": payload.hidden_reason,
            },
        )
    )
    await session.commit()
    await session.refresh(comment)
    author = await session.scalar(select(User).where(User.id == comment.author_user_id))
    return _comment_to_response(comment, author_email=author.email if author else None)


# --- owner endpoints ------------------------------------------------------


@me_router.get(
    "/properties/{property_id}/announcements",
    response_model=list[AnnouncementResponse],
)
async def my_list_announcements(
    property_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AnnouncementResponse]:
    """Portal list — published announcements, audience-filtered to the
    caller's role. Soft-deleted rows excluded."""
    await _load_property_for_owner(session, user=current_user, property_id=property_id)
    rows, _ = await svc.list_for_property_owner(
        session,
        user=current_user,
        property_id=property_id,
        limit=limit,
        offset=offset,
    )
    return await _enrich_summaries(session, rows)


@me_router.get(
    "/announcements/{announcement_id}",
    response_model=AnnouncementDetailResponse,
)
async def my_get_announcement(
    announcement_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AnnouncementDetailResponse:
    """Portal detail — only published + audience-matched. The
    property-visibility check uses the same `_visible_properties_stmt`
    helper as the rest of /me."""
    announcement = await svc.get_owner(session, announcement_id=announcement_id, user=current_user)
    if announcement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found",
        )
    # Re-verify the property is in the caller's visible set —
    # `get_owner` deliberately doesn't couple to the API layer.
    await _load_property_for_owner(session, user=current_user, property_id=announcement.property_id)
    summary = await _enrich_response(session, announcement)
    attachments = await svc.list_attachments(session, announcement.id)
    comments = await svc.list_comments(session, announcement.id, include_hidden=False)
    return AnnouncementDetailResponse(
        **summary.model_dump(),
        attachments=[AnnouncementAttachmentResponse.model_validate(a) for a in attachments],
        comments=await _comments_with_emails(session, comments),
    )


@me_router.get("/announcements/{announcement_id}/attachments/{attachment_id}/download")
async def my_download_attachment(
    announcement_id: uuid.UUID,
    attachment_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    announcement = await svc.get_owner(session, announcement_id=announcement_id, user=current_user)
    if announcement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found",
        )
    await _load_property_for_owner(session, user=current_user, property_id=announcement.property_id)
    attachment = await session.scalar(
        select(AnnouncementAttachment).where(
            AnnouncementAttachment.id == attachment_id,
            AnnouncementAttachment.announcement_id == announcement.id,
        )
    )
    if attachment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found",
        )
    return _serve_attachment(attachment)


@me_router.post(
    "/announcements/{announcement_id}/comments",
    response_model=AnnouncementCommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def my_create_comment(
    announcement_id: uuid.UUID,
    payload: AnnouncementCommentCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
) -> AnnouncementCommentResponse:
    """Post a comment under a published announcement.

    Requires: announcement is published + audience-matches + caller
    has access to the property. On success, fires a "new comment"
    notification to the Verwalter team + everyone who has already
    commented on this announcement (excl. the new commenter, hidden
    commenters); failures don't roll back the comment.
    """
    announcement = await svc.get_owner(session, announcement_id=announcement_id, user=current_user)
    if announcement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found",
        )
    await _load_property_for_owner(session, user=current_user, property_id=announcement.property_id)
    comment = svc.add_comment(
        session,
        announcement=announcement,
        author=current_user,
        body=payload.body,
    )
    await session.flush()
    session.add(
        AuditLog(
            organization_id=announcement.organization_id,
            actor_user_id=current_user.id,
            action="announcement_comment_created",
            target_type="announcement_comments",
            target_id=str(comment.id),
            payload_json={
                "announcement_id": str(announcement.id),
                "body_length": len(payload.body),
            },
        )
    )
    await session.commit()
    await session.refresh(comment)

    # Fan-out the "new comment" notification. Best-effort — a Resend
    # hiccup doesn't reverse the commit (the user already saw their
    # comment go in). Resolve recipients after the commit so the new
    # comment is included in the prior-commenter check on retries.
    try:
        recipients = await svc.resolve_comment_notification_recipients(
            session, announcement=announcement, new_comment=comment
        )
        if recipients:
            prop = await session.scalar(
                select(Property).where(Property.id == announcement.property_id)
            )
            property_name = prop.name if prop else "—"
            subject, html, text = render_comment_notification_email(
                announcement_id=str(announcement.id),
                announcement_title=announcement.title,
                property_name=property_name,
                commenter_label=current_user.email,
                comment_body=payload.body,
                commented_at=comment.created_at,
            )
            for r in recipients:
                if not r.email:
                    continue
                try:
                    await email_client.send(
                        to=[r.email],
                        subject=subject,
                        html=html,
                        text=text,
                    )
                except EmailError:
                    logger.warning(
                        "comment notification send failed: announcement=%s recipient=%s",
                        announcement.id,
                        r.email,
                    )
    except Exception:
        # Never let notification fan-out crash the request — the
        # comment is already committed.
        logger.exception(
            "comment notification fan-out failed for announcement=%s",
            announcement.id,
        )

    return _comment_to_response(comment, author_email=current_user.email)


@me_router.patch(
    "/announcements/{announcement_id}/comments/{comment_id}",
    response_model=AnnouncementCommentResponse,
)
async def my_edit_comment(
    announcement_id: uuid.UUID,
    comment_id: uuid.UUID,
    payload: AnnouncementCommentEditRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AnnouncementCommentResponse:
    """Edit your own comment. 404 if the comment doesn't exist, belongs
    to a different announcement, or you're not the author — we don't
    distinguish to avoid leaking the existence of other people's
    comments. Admin moderation runs on a separate URL."""
    announcement = await svc.get_owner(session, announcement_id=announcement_id, user=current_user)
    if announcement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found",
        )
    await _load_property_for_owner(session, user=current_user, property_id=announcement.property_id)
    comment: AnnouncementComment | None = await session.scalar(
        select(AnnouncementComment).where(
            AnnouncementComment.id == comment_id,
            AnnouncementComment.announcement_id == announcement.id,
        )
    )
    # Single 404 covers both "no such comment" and "not your comment".
    if comment is None or comment.author_user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    try:
        svc.edit_comment(session, comment=comment, author=current_user, new_body=payload.body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    session.add(
        AuditLog(
            organization_id=announcement.organization_id,
            actor_user_id=current_user.id,
            action="announcement_comment_edited",
            target_type="announcement_comments",
            target_id=str(comment.id),
            payload_json={
                "announcement_id": str(announcement.id),
                "body_length": len(payload.body),
            },
        )
    )
    await session.commit()
    await session.refresh(comment)
    return _comment_to_response(comment, author_email=current_user.email)


async def _load_comment_for_history(
    session: AsyncSession,
    *,
    announcement_id: uuid.UUID,
    comment_id: uuid.UUID,
    requester: User,
    admin: bool,
) -> AnnouncementComment:
    """Resolve a comment for the version-history endpoint.

    Admins can read any comment in their org's announcements. Portal
    callers can only read their own comments' history (and only if
    they can see the parent announcement at all). Returns the comment
    row on success; raises 404 on miss / wrong scope (no existence
    leak).
    """
    if admin:
        # Admin path: join the comment to its announcement and gate
        # by org.
        row: AnnouncementComment | None = await session.scalar(
            select(AnnouncementComment)
            .join(
                Announcement,
                Announcement.id == AnnouncementComment.announcement_id,
            )
            .where(
                AnnouncementComment.id == comment_id,
                AnnouncementComment.announcement_id == announcement_id,
                Announcement.organization_id == requester.organization_id,
            )
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
        return row

    # Owner path: full visibility chain — announcement is published,
    # audience-matches, caller can access the property, AND caller
    # is the comment's author.
    announcement = await svc.get_owner(session, announcement_id=announcement_id, user=requester)
    if announcement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Announcement not found")
    await _load_property_for_owner(session, user=requester, property_id=announcement.property_id)
    own_row: AnnouncementComment | None = await session.scalar(
        select(AnnouncementComment).where(
            AnnouncementComment.id == comment_id,
            AnnouncementComment.announcement_id == announcement.id,
        )
    )
    if own_row is None or own_row.author_user_id != requester.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    return own_row


@me_router.get(
    "/announcements/{announcement_id}/comments/{comment_id}/versions",
    response_model=list[AnnouncementCommentVersionResponse],
)
async def my_list_comment_versions(
    announcement_id: uuid.UUID,
    comment_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AnnouncementCommentVersionResponse]:
    """Versions of *your own* comment, newest first. 404 for someone
    else's comment (no existence leak)."""
    await _load_comment_for_history(
        session,
        announcement_id=announcement_id,
        comment_id=comment_id,
        requester=current_user,
        admin=False,
    )
    rows = await svc.list_comment_versions(session, comment_id)
    return [AnnouncementCommentVersionResponse.model_validate(r) for r in rows]


@admin_router.get(
    "/announcements/{announcement_id}/comments/{comment_id}/versions",
    response_model=list[AnnouncementCommentVersionResponse],
)
async def admin_list_comment_versions(
    announcement_id: uuid.UUID,
    comment_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AnnouncementCommentVersionResponse]:
    """Admin moderation reads any comment's history in the org."""
    await _load_comment_for_history(
        session,
        announcement_id=announcement_id,
        comment_id=comment_id,
        requester=current_user,
        admin=True,
    )
    rows = await svc.list_comment_versions(session, comment_id)
    return [AnnouncementCommentVersionResponse.model_validate(r) for r in rows]
