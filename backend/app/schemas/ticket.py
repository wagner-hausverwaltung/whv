import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import TicketCategory, TicketStatus


class TicketCreateRequest(BaseModel):
    subject: str = Field(..., min_length=3, max_length=200)
    body: str = Field(..., min_length=3, max_length=10_000)
    category: TicketCategory
    property_id: uuid.UUID | None = None


class TicketMessageCreateRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=10_000)
    is_internal_note: bool = False


class TicketStatusUpdateRequest(BaseModel):
    status: TicketStatus
    assignee_user_id: uuid.UUID | None = None


class TicketMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID
    author_user_id: uuid.UUID
    body: str
    is_internal_note: bool
    created_at: datetime


class TicketResponse(BaseModel):
    """Summary row for queue + list views — no messages."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    property_id: uuid.UUID | None
    created_by_user_id: uuid.UUID
    assignee_user_id: uuid.UUID | None
    category: TicketCategory
    status: TicketStatus
    subject: str
    last_message_at: datetime
    created_at: datetime
    closed_at: datetime | None


class TicketDetailResponse(TicketResponse):
    """Detail view with full thread. For non-Verwalter callers, the handler
    filters `messages` to exclude `is_internal_note=True` rows before
    serialization."""

    messages: list[TicketMessageResponse]
