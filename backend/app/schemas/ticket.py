import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import TicketCategory, TicketShareScope, TicketStatus


class TicketCreateRequest(BaseModel):
    subject: str = Field(..., min_length=3, max_length=200)
    body: str = Field(..., min_length=3, max_length=10_000)
    category: TicketCategory
    property_id: uuid.UUID | None = None
    # Optional initial sharing — defaults to PRIVATE if omitted. PROPERTY
    # requires property_id to also be set; the handler validates this.
    share_scope: TicketShareScope = TicketShareScope.PRIVATE


class TicketMessageCreateRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=10_000)
    is_internal_note: bool = False


class TicketStatusUpdateRequest(BaseModel):
    status: TicketStatus
    assignee_user_id: uuid.UUID | None = None


class TicketShareScopeUpdateRequest(BaseModel):
    share_scope: TicketShareScope


class TicketParticipantAddRequest(BaseModel):
    email: EmailStr


class TicketParticipantResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    added_by_user_id: uuid.UUID
    added_at: datetime


class TicketMessageAttachmentResponse(BaseModel):
    """One file attached to a ticket message — uploaded via the SPA or
    extracted from an inbound email's MIME tree. The actual bytes are
    fetched from `/<scope>/tickets/{ticket_id}/attachments/{id}/file`
    (authenticated, scope-checked)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_message_id: uuid.UUID
    filename: str
    mime_type: str | None = None
    size_bytes: int
    uploaded_by_user_id: uuid.UUID | None = None
    created_at: datetime


class TicketMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID
    # NULL when the message arrived from a non-registered email sender;
    # external_sender_email on the parent ticket then identifies them.
    author_user_id: uuid.UUID | None = None
    # Author email is resolved server-side so the SPA doesn't have to make
    # a second batch lookup. None if the user has been hard-deleted.
    author_email: str | None = None
    body: str
    is_internal_note: bool
    created_at: datetime
    # Eagerly-loaded per-message attachments. Empty list when the message
    # had none — keeps the SPA render simple (no null-check on every row).
    attachments: list[TicketMessageAttachmentResponse] = []


class TicketResponse(BaseModel):
    """Summary row for queue + list views — no messages, no participants.

    Denormalised join fields (property_name + address, creator_email +
    contact label) are populated by the list handlers so the SPA tile can
    render without N+1 follow-up requests. They are optional on the model
    because the create-ticket handler returns a fresh row before joins are
    resolved.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    property_id: uuid.UUID | None
    created_by_user_id: uuid.UUID
    assignee_user_id: uuid.UUID | None
    category: TicketCategory
    status: TicketStatus
    share_scope: TicketShareScope
    subject: str
    last_message_at: datetime
    created_at: datetime
    closed_at: datetime | None

    # Denormalised context for the queue tile. None when the join target
    # doesn't exist (e.g. ticket has no property, or the creator was
    # hard-deleted) or when the handler hasn't fetched them (single-row
    # create response).
    property_name: str | None = None
    property_address: str | None = None
    creator_email: str | None = None
    creator_contact_label: str | None = None
    creator_contact_id_impower: int | None = None
    external_sender_email: str | None = None


class TicketDetailResponse(TicketResponse):
    """Detail view with full thread + participants. For non-Verwalter callers,
    the handler filters `messages` to exclude `is_internal_note=True` rows
    before serialization."""

    messages: list[TicketMessageResponse]
    participants: list[TicketParticipantResponse]
