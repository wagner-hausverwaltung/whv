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


class AdminDashboardStats(BaseModel):
    """Counts shown on the admin SPA dashboard.

    Numbers are scoped to the caller's organization. Mirrors what the
    Jinja dashboard.html template displays today; the SPA reads this JSON
    instead of being a server-rendered page.
    """

    pending_invites: int
    consumed_invites: int
    properties: int
    units: int
    contracts: int
    contacts: int
    open_tickets: int
    open_resolutions: int


class AdminPropertySearchResult(BaseModel):
    """Slim property row for the SPA invite/resolution typeahead picker."""

    id: uuid.UUID
    name: str
    property_hr_id: str | None = None
    city: str | None = None
    street: str | None = None


class AdminContactSearchResult(BaseModel):
    """Slim contact row for the contact typeahead, keyed by Impower ID.

    The invite form needs the Impower ID (not the WHV UUID) to link the
    new account to the right Eigentümer / Mieter on the next sync; the
    UUID would be opaque after a re-sync.
    """

    impower_id: int
    label: str  # display name (company OR first + last)
    email: str | None = None


class AdminAuditLogResponse(BaseModel):
    """Row in the admin audit-log viewer.

    `actor_email` is denormalised at read time so the SPA renders the
    table without a follow-up user lookup. May be None if the actor user
    was hard-deleted (FK is ON DELETE SET NULL).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    actor_email: str | None = None
    action: str
    target_type: str | None
    target_id: str | None
    payload_json: dict[str, Any] | None
    created_at: datetime
