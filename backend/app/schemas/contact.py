"""Schemas for the portal/iOS contact-detail dialog.

Exposed via `GET /me/contracts/{contract_id}/contacts/{contact_id}`,
which underpins the clickable contract-chip flow on the property
detail view — owners and tenants can tap their name to see what we
have on file.

We return everything the API mirrors except the raw JSONB blob (that
carries Impower-internal fields the customer-facing UI shouldn't
surface). For Mieter / Eigentümer this is "see your own data";
for Beirat / Verwalter it's the same person-card they'd otherwise
need the admin SPA to inspect.
"""

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict

from app.models.contact import ContactKind, PreferredChannel
from app.models.contract import ContractType


class ContractContextResponse(BaseModel):
    """The contract that wires this contact to the property — the
    "why am I looking at this person" half of the dialog."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: ContractType
    contract_number: str | None = None
    name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_vacant: bool | None = None
    # From the join row — typically empty in practice, but when
    # populated it carries useful nuance ("Hauptmieter" vs.
    # "Mitmieter") that the type alone doesn't capture.
    role: str | None = None


class ContactDetailResponse(BaseModel):
    """Full contact card returned to the portal + iOS sheet."""

    model_config = ConfigDict(from_attributes=True)

    # Identity
    id: uuid.UUID
    kind: ContactKind
    # Person fields — null on companies and vice versa.
    salutation: str | None = None
    title: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    # Company fields
    company_name: str | None = None
    vat_id: str | None = None
    trade_register_number: str | None = None
    # Communications
    recipient_name: str | None = None
    mandate_number: str | None = None
    email: str | None = None
    phone: str | None = None
    preferred_channel: PreferredChannel
    # Free-form alternate channels Impower lets the user enter ("Tel
    # geschäftlich", "Mobil Partner", etc.). Just a dict; the SPA
    # renders it as key/value lines.
    additional_contacts: dict[str, object] | None = None
    # Address
    city: str | None = None
    street: str | None = None
    number: str | None = None
    postal_code: str | None = None
    country: str | None = None

    # Contract context
    contract: ContractContextResponse
