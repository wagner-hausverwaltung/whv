"""Pydantic schemas for announcements (Mitteilungen).

Request shapes carry input from the SPA / admin API; response shapes are
returned to both admin and portal callers. Audience flags carry a
`model_validator` on create-side schemas; the update-side cannot check
"at least one" alone because a partial PATCH may set only one flag and
the resolved state depends on the DB row — that check lives in
`app/services/announcements.update_announcement`.
"""

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AnnouncementCreateRequest(BaseModel):
    """Admin compose payload. At least one audience flag must be true."""

    title: str = Field(..., min_length=1, max_length=200)
    # Body is optional on create — the admin might compose-and-edit, or
    # send a "Strom fällt morgen 9-11 Uhr aus" headline-only update.
    body: str = Field("", max_length=20_000)
    audience_eigentuemer: bool = True
    audience_mieter: bool = True
    audience_beirat: bool = True

    @model_validator(mode="after")
    def _at_least_one_audience(self) -> Self:
        if not (self.audience_eigentuemer or self.audience_mieter or self.audience_beirat):
            raise ValueError(
                "At least one audience flag (Eigentümer / Mieter / Beirat) must be selected"
            )
        return self


class AnnouncementUpdateRequest(BaseModel):
    """All fields optional — admin can PATCH any subset.

    Audience-at-least-one is validated in the service layer against the
    *resolved* row (DB + patch), since a partial PATCH carries only the
    flags being changed.
    """

    title: str | None = Field(None, min_length=1, max_length=200)
    body: str | None = Field(None, max_length=20_000)
    audience_eigentuemer: bool | None = None
    audience_mieter: bool | None = None
    audience_beirat: bool | None = None


class AnnouncementCommentCreateRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=10_000)


class AnnouncementCommentEditRequest(BaseModel):
    """Author-only inline edit. Admin moderation uses the separate
    `AnnouncementCommentModerationRequest` shape; this endpoint
    explicitly does not allow admin edits to user content."""

    body: str = Field(..., min_length=1, max_length=10_000)


class AnnouncementCommentModerationRequest(BaseModel):
    """Admin hide / unhide. Setting is_hidden=False clears hidden_reason
    + hidden_at + hidden_by_user_id in the service helper."""

    is_hidden: bool
    hidden_reason: str | None = Field(None, max_length=500)


class AnnouncementAttachmentResponse(BaseModel):
    """One file attached to an announcement. Bytes fetched from
    `/<scope>/announcements/{id}/attachments/{aid}/download`
    (authenticated, scope-checked)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    announcement_id: uuid.UUID
    filename: str
    mime_type: str | None = None
    size_bytes: int
    uploaded_by_user_id: uuid.UUID | None = None
    created_at: datetime


class AnnouncementCommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    announcement_id: uuid.UUID
    author_user_id: uuid.UUID
    # Resolved server-side so the SPA renders the byline without a
    # second batch lookup. None if the author has been hard-deleted.
    author_email: str | None = None
    body: str
    created_at: datetime
    updated_at: datetime
    # Author-edit timestamp. NULL when the comment was never edited.
    # Portal renders a "bearbeitet am …" hint when this is set.
    edited_at: datetime | None = None

    # Moderation fields. For non-admin responses, hidden comments are
    # filtered out before serialisation, so these always read false/null
    # in that case. Admin responses get the real values.
    is_hidden: bool = False
    hidden_at: datetime | None = None
    hidden_by_user_id: uuid.UUID | None = None
    hidden_reason: str | None = None


class AnnouncementResponse(BaseModel):
    """Summary row for list views — no attachments, no comments.

    `is_edited` is resolved server-side from `updated_at` vs.
    `notification_sent_at`: True when the row was touched more than 60s
    after publish. Keeps the SPA from doing its own time math.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    property_id: uuid.UUID
    created_by_user_id: uuid.UUID
    title: str
    body: str
    audience_eigentuemer: bool
    audience_mieter: bool
    audience_beirat: bool
    created_at: datetime
    updated_at: datetime
    scheduled_publish_at: datetime
    # NULL until the fan-out task succeeds — doubles as the "is
    # published" flag for the SPA.
    notification_sent_at: datetime | None = None

    # Denormalised join + computed fields. Populated by the list +
    # detail handlers; never come straight from the ORM.
    property_name: str | None = None
    creator_email: str | None = None
    is_edited: bool = False
    attachment_count: int = 0
    comment_count: int = 0


class AnnouncementDetailResponse(AnnouncementResponse):
    """Detail view with the full attachment list + comments thread."""

    attachments: list[AnnouncementAttachmentResponse] = []
    comments: list[AnnouncementCommentResponse] = []
