"""Verwalter-side contact helpers for the car / Siri.

  GET  /me/contacts/search?q=      contacts on active objects (for "WHV Notiz an …")
  POST /me/contacts/{id}/message   e-mail a short message to one contact

Both Verwalter-only: owners never see the org's contact list, and sending
mail on WHV's behalf is a Verwalter action. The message goes out server-side
via Resend with reply-to = the Verwalter (same pattern as the delay notice)
and is audited.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db import get_session
from app.integrations.email.client import EmailClient, EmailError, get_email_client
from app.models import (
    AuditLog,
    Contact,
    Contract,
    ContractContact,
    ContractType,
    Property,
    User,
    UserRole,
)
from app.services.access import active_property_filter
from app.services.units import _contact_label

me_router = APIRouter(prefix="/me/contacts", tags=["verwalter-contacts"])
_verwalter_only = require_role(UserRole.VERWALTER)

_ROLE_LABEL = {
    ContractType.OWNER: "Eigentümer",
    ContractType.PROPERTY_OWNER: "Eigentümer",
    ContractType.TENANT: "Mieter",
}


class ContactSearchResult(BaseModel):
    id: uuid.UUID
    name: str
    email: str | None
    phone: str | None
    property_name: str | None
    role: str | None


class ContactMessageRequest(BaseModel):
    text: str = Field(min_length=2, max_length=4000)
    subject: str | None = Field(default=None, max_length=200)


class ContactMessageResponse(BaseModel):
    sent: bool
    to: str | None
    detail: str


@me_router.get("/search", response_model=list[ContactSearchResult])
async def search_contacts(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str, Query(max_length=100)] = "",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[ContactSearchResult]:
    """Contacts holding a current contract on an active object, by name.
    Empty `q` returns the first `limit` alphabetically (Siri's suggestion
    list); a query matches first/last/company name (case-insensitive)."""
    today = date.today()
    stmt = (
        select(Contact, Property.name, Contract.type)
        .join(ContractContact, ContractContact.contact_id == Contact.id)
        .join(Contract, Contract.id == ContractContact.contract_id)
        .join(Property, Property.id == Contract.property_id)
        .where(
            Contact.organization_id == current_user.organization_id,
            Contact.deleted_at.is_(None),
            Contract.deleted_at.is_(None),
            or_(Contract.end_date.is_(None), Contract.end_date >= today),
            active_property_filter(),
        )
        .order_by(Contact.last_name, Contact.company_name, Contact.first_name)
    )
    q_stripped = q.strip()
    if q_stripped:
        like = f"%{q_stripped}%"
        stmt = stmt.where(
            Contact.first_name.ilike(like)
            | Contact.last_name.ilike(like)
            | Contact.company_name.ilike(like)
        )
    rows = (await session.execute(stmt.limit(limit * 4))).all()
    out: list[ContactSearchResult] = []
    seen: set[uuid.UUID] = set()
    for contact, prop_name, ctype in rows:
        if contact.id in seen:
            continue
        seen.add(contact.id)
        out.append(
            ContactSearchResult(
                id=contact.id,
                name=_contact_label(contact),
                email=contact.email,
                phone=contact.phone,
                property_name=prop_name,
                role=_ROLE_LABEL.get(ctype),
            )
        )
        if len(out) >= limit:
            break
    return out


@me_router.post("/{contact_id}/message", response_model=ContactMessageResponse)
async def message_contact(
    contact_id: uuid.UUID,
    req: ContactMessageRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
) -> ContactMessageResponse:
    """Send a short message (dictated in the car via Siri) to a contact by
    e-mail, on behalf of WHV, reply-to the Verwalter. No e-mail on file →
    sent=false with a reason (Siri reads it back)."""
    contact = await session.scalar(
        select(Contact).where(
            Contact.id == contact_id,
            Contact.organization_id == current_user.organization_id,
            Contact.deleted_at.is_(None),
        )
    )
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kontakt nicht gefunden")
    if not contact.email:
        return ContactMessageResponse(
            sent=False, to=None, detail="Kontakt hat keine E-Mail-Adresse."
        )

    sender = current_user.email.split("@", 1)[0].replace(".", " ").title()
    subject = (req.subject or "").strip() or f"Nachricht von {sender} (Wagner Hausverwaltung)"
    text = (
        f"Guten Tag {_contact_label(contact)},\n\n"
        f"{req.text.strip()}\n\n"
        f"Freundliche Grüße\n{sender}\nWagner Hausverwaltung GmbH\n\n"
        "Sie können direkt auf diese E-Mail antworten."
    )
    html = "<p>" + text.replace("\n", "<br>") + "</p>"
    try:
        await email_client.send(
            to=contact.email,
            subject=subject,
            html=html,
            text=text,
            reply_to=current_user.email,
        )
    except EmailError as exc:
        return ContactMessageResponse(
            sent=False, to=contact.email, detail=f"Versand fehlgeschlagen: {exc}"
        )
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="contact_message_sent",
            target_type="contacts",
            target_id=str(contact.id),
            payload_json={"subject": subject, "chars": len(req.text)},
        )
    )
    await session.commit()
    return ContactMessageResponse(
        sent=True, to=contact.email, detail=f"Nachricht an {_contact_label(contact)} gesendet."
    )
