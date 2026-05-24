import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models import UserRole


class InviteStatus(StrEnum):
    PENDING = "pending"
    CONSUMED = "consumed"
    EXPIRED = "expired"


class CreateInviteRequest(BaseModel):
    email: EmailStr
    role: UserRole
    contact_id_impower: int | None = None
    scope_json: dict[str, Any] | None = None
    ttl_days: int = 14


class AdminInviteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    email: EmailStr
    role: UserRole
    contact_id_impower: int | None = None
    scope_json: dict[str, Any] | None = None
    expires_at: datetime
    consumed_at: datetime | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime
    # Per-response convenience flag, computed from consumed_at + expires_at
    status: InviteStatus = InviteStatus.PENDING
    # Resend message id if the email was sent at create time. May be None
    # if email send failed (the invite is still created and can be resent).
    email_message_id: str | None = None
