"""Caller ID for the Verwalter's phone — `GET /me/call-directory`.

iOS CallKit lets an app ship a Call Directory Extension that labels
incoming calls. The app (Verwalter only) pulls this list, writes it to the
shared app-group container and asks CallKit to reload the extension; from
then on a call from an owner, tenant or vendor shows "Franziska Fritz ·
WEG Hasenbergstr. 32 (Eigentümer)" on the phone and on the car display.

CallKit wants numbers as ascending unique integers (E.164 digits without the
"+"), so the normalisation and the de-duplication happen here, once, rather
than in the extension that runs under tight memory limits.
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db import get_session
from app.models import Contact, Contract, ContractContact, ContractType, Property, User, UserRole
from app.services.units import _contact_label

me_router = APIRouter(prefix="/me", tags=["call-directory"])

_verwalter_only = require_role(UserRole.VERWALTER)

# Labels longer than this are cut by the phone UI anyway; keep them scannable.
_LABEL_MAX = 60
_ROLE_LABEL = {
    ContractType.OWNER: "Eigentümer",
    ContractType.PROPERTY_OWNER: "Eigentümer",
    ContractType.TENANT: "Mieter",
}


class CallDirectoryEntry(BaseModel):
    number: int  # E.164 digits, e.g. 4971112345 — CallKit's CXCallDirectoryPhoneNumber
    label: str


class CallDirectoryResponse(BaseModel):
    entries: list[CallDirectoryEntry]
    contacts: int


def normalize_phone(raw: str | None, default_country: str = "49") -> int | None:
    """'+49 711 123-45', '0711/12345', '0049711…', '0176 1234567' → 49711…;
    None when there is nothing dialable (extensions, placeholders)."""
    if not raw:
        return None
    s = raw.strip()
    # Drop a trailing extension ("-12", " Durchwahl 12") and anything that is
    # not a digit or leading plus.
    s = re.split(r"(?i)\s*(durchwahl|dw\.?|ext\.?|x)\s*\d*$", s)[0]
    plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if not digits:
        return None
    if plus:
        pass
    elif digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = default_country + digits[1:]
    else:
        # Neither international nor trunk prefix: treat as national number
        # without the 0 (rare) — still prefix the country.
        digits = default_country + digits
    if len(digits) < 7 or len(digits) > 15:
        return None
    return int(digits)


def short_property_name(name: str) -> str:
    """'WEG Hasenbergstraße 32, 70176 Stuttgart' → 'WEG Hasenbergstr. 32' —
    the street keeps the label short enough for the call screen."""
    head = name.split(",", 1)[0].strip()
    return head.replace("straße", "str.").replace("Straße", "Str.")


def build_label(name: str, memberships: list[tuple[str, str]]) -> str:
    """'Franziska Fritz · WEG Hasenbergstr. 32 (Eigentümer)' (+N weitere)."""
    if not memberships:
        return name[:_LABEL_MAX]
    prop, role = memberships[0]
    label = f"{name} · {short_property_name(prop)} ({role})"
    if len(memberships) > 1:
        label += f" +{len(memberships) - 1}"
    if len(label) > _LABEL_MAX:
        label = label[: _LABEL_MAX - 1].rstrip() + "…"
    return label


@me_router.get("/call-directory", response_model=CallDirectoryResponse)
async def my_call_directory(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CallDirectoryResponse:
    """Every contact with a phone number that currently holds a contract on
    one of the org's (active) properties, labelled with name, object and role.
    Sorted ascending by number, one entry per number (CallKit requirement)."""
    today = date.today()
    rows = (
        await session.execute(
            select(Contact, Property.name, Contract.type)
            .join(ContractContact, ContractContact.contact_id == Contact.id)
            .join(Contract, Contract.id == ContractContact.contract_id)
            .join(Property, Property.id == Contract.property_id)
            .where(
                Contact.organization_id == current_user.organization_id,
                Contact.deleted_at.is_(None),
                Contact.phone.is_not(None),
                Contract.deleted_at.is_(None),
                or_(Contract.end_date.is_(None), Contract.end_date >= today),
                Property.deleted_at.is_(None),
            )
            .order_by(Property.name)
        )
    ).all()

    # contact → memberships; then number → (name, memberships)
    per_contact: dict[uuid.UUID, tuple[Contact, list[tuple[str, str]]]] = {}
    for contact, prop_name, ctype in rows:
        entry = per_contact.setdefault(contact.id, (contact, []))
        role = _ROLE_LABEL.get(ctype, str(ctype))
        if (prop_name, role) not in entry[1]:
            entry[1].append((prop_name, role))

    by_number: dict[int, list[str]] = {}
    for contact, memberships in per_contact.values():
        number = normalize_phone(contact.phone)
        if number is None:
            continue
        label = build_label(_contact_label(contact), memberships)
        labels = by_number.setdefault(number, [])
        if label not in labels:
            labels.append(label)

    entries = [
        CallDirectoryEntry(number=n, label=(" / ".join(labels))[:_LABEL_MAX])
        for n, labels in sorted(by_number.items())
    ]
    return CallDirectoryResponse(entries=entries, contacts=len(per_contact))


__all__ = ["build_label", "me_router", "normalize_phone", "short_property_name"]
