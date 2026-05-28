import uuid
from datetime import date, datetime
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


class AdminPropertyContactInviteInfo(BaseModel):
    """Compact snapshot of the contact's currently-pending invite, if
    any. None means no unconsumed + unexpired invite exists; the UI
    surfaces this as "Einladen" vs. "Erneut senden"."""

    code: str
    expires_at: datetime
    created_at: datetime


class AdminPropertyContactResponse(BaseModel):
    """One contact linked to the property via a contract, enriched
    with their account / invite status for the Einladungen tab.

    `suggested_role` is inferred from the contract type — OWNER and
    PROPERTY_OWNER map to EIGENTUEMER, TENANT maps to MIETER. The
    Verwalter can still override via the per-contact action.
    """

    contact_id: uuid.UUID
    impower_id: int | None
    name: str
    email: str | None
    contract_type: str  # raw enum value for the UI badge
    suggested_role: UserRole
    has_user_account: bool
    pending_invite: AdminPropertyContactInviteInfo | None = None
    last_invited_at: datetime | None = None


class BulkInviteRequest(BaseModel):
    """Bulk-invite N contacts on a property. The endpoint infers each
    invite's role from the contact's contract type; if a contact has
    no clear role mapping, it's skipped with `skipped_no_role`."""

    contact_ids: list[uuid.UUID]
    ttl_days: int = 14


class BulkInviteOutcomeStatus(StrEnum):
    SENT = "sent"  # fresh invite created + email sent
    RESENT = "resent"  # old code invalidated, new code created + sent
    SKIPPED_ACCOUNT_EXISTS = "skipped_account_exists"
    SKIPPED_NO_EMAIL = "skipped_no_email"
    SKIPPED_NO_ROLE = "skipped_no_role"
    FAILED = "failed"


class BulkInviteOutcome(BaseModel):
    contact_id: uuid.UUID
    status: BulkInviteOutcomeStatus
    code: str | None = None
    email: str | None = None
    reason: str | None = None  # populated on FAILED


class BulkInviteResponse(BaseModel):
    outcomes: list[BulkInviteOutcome]


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


class AdminPropertyDetailResponse(BaseModel):
    """Admin property detail with counts for the right-hand tabs.

    Master-data fields come from the Property row; counts are computed at
    read time and scoped to the caller's organisation. Drives the
    /admin/properties/:id page in the SPA — Overview tab consumes the
    base fields, Tickets/Companies tabs trigger their own queries.
    """

    id: uuid.UUID
    name: str
    impower_id: int | None = None
    property_hr_id: str | None = None
    type: str
    state: str
    city: str | None = None
    street: str | None = None
    number: str | None = None
    postal_code: str | None = None
    country: str | None = None
    image_url: str | None = None
    units_count: int
    contracts_count: int
    contacts_count: int
    open_tickets_count: int
    open_resolutions_count: int
    invoice_companies_count: int


class AdminPropertyCompanyResponse(BaseModel):
    """A vendor company that's been billed against this property.

    Distinct contact rows that appear as `documents.contact_id` on at
    least one Document with `kind=RECHNUNG` for the property. Includes
    aggregate stats (invoice count, sum of amounts, most-recent date)
    so the operator sees who they spend money with at a glance.
    """

    contact_id: uuid.UUID
    impower_id: int | None = None
    name: str
    email: str | None = None
    phone: str | None = None
    invoice_count: int
    total_amount: float | None = None
    most_recent_invoice_at: datetime | None = None


class AdminPropertyListItem(BaseModel):
    """Slim property row for the SPA /admin/properties table."""

    id: uuid.UUID
    name: str
    property_hr_id: str | None = None
    type: str
    state: str
    city: str | None = None
    street: str | None = None
    number: str | None = None
    postal_code: str | None = None
    image_url: str | None = None
    # Number of (non-deleted) units — drives the selectable units/salary
    # summary box in the admin table.
    units_count: int = 0
    # True when the property has NO non-cancelled ETV scheduled in the
    # current calendar year (one ETV/year is expected), so the Verwalter
    # can spot open ETVs at a glance.
    needs_current_year_etv: bool = False


class AdminPropertySelectionResponse(BaseModel):
    """The org-wide set of property ids checked for the units/fee box —
    shared by all Verwalter of the organization."""

    property_ids: list[uuid.UUID]


class AdminPropertySelectionUpdate(BaseModel):
    property_ids: list[uuid.UUID]


class AdminUnitListItem(BaseModel):
    """Unit row joined to its property name for the /admin/units table.

    Distribution-key fields (voting_share / area_m2 / heated_area_m2 /
    persons) come from manual Verwalter entry — Impower's REST API
    doesn't expose them. See ADR-0009.
    """

    id: uuid.UUID
    unit_hr_id: str | None = None
    type: str
    floor: str | None = None
    position: str | None = None
    voting_share: float | None = None
    area_m2: float | None = None
    heated_area_m2: float | None = None
    persons: float | None = None
    property_id: uuid.UUID
    property_name: str
    property_type: str


class AdminUnitDistributionKeysUpdate(BaseModel):
    """PUT body for /admin/units/{id}/distribution-keys. Every field
    is optional — sending only the ones the Verwalter changed keeps
    the audit-log entry tight and lets a future browser-extension
    bulk-fill skip fields Impower didn't render."""

    voting_share: float | None = None
    area_m2: float | None = None
    heated_area_m2: float | None = None
    persons: float | None = None


class AdminContractListItem(BaseModel):
    """Contract row joined to its property for /admin/contracts."""

    id: uuid.UUID
    type: str
    contract_number: str | None = None
    name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_vacant: bool | None = None
    property_id: uuid.UUID
    property_name: str


class AdminContactListItem(BaseModel):
    """Contact row for /admin/contacts. `name` is the precomputed display
    label (company name for COMPANY contacts, otherwise first + last)."""

    id: uuid.UUID
    impower_id: int | None = None
    kind: str
    name: str
    email: str | None = None
    phone: str | None = None
    city: str | None = None


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
