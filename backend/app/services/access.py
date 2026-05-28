"""Shared access-control predicates.

`active_contract_filter` is the single source of truth for "does this
contract still grant access?". A contract whose `end_date` has passed
(owner sold their unit, tenant moved out) must stop conferring portal
visibility AND stop pulling the person into notification fan-outs —
otherwise a former owner keeps seeing (and being emailed/pushed about)
a Liegenschaft they no longer belong to. Used by every query that
reaches a property/document through `contracts`.

Decision (2026-05-28): hard cutoff at `end_date`. We deliberately do
NOT also gate on `start_date` — a new owner/tenant whose contract
starts slightly in the future should still be able to onboard.
NULL `end_date` = open-ended = active.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Contact, Contract, ContractContact, User, UserRole


def active_contract_filter(today: date | None = None) -> ColumnElement[bool]:
    """SQLAlchemy boolean: the contract is still active as of `today`."""
    if today is None:
        today = date.today()
    return or_(Contract.end_date.is_(None), Contract.end_date >= today)


async def owner_users_for_property(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    property_id: uuid.UUID,
) -> list[User]:
    """Portal users who are owners of a property: EIGENTUEMER + BEIRAT
    (Beirat members are elected owners) reachable via an ACTIVE contract
    on that property. Excludes Mieter and former owners. Used by
    owner-facing fan-outs (ETV invitations, booked-invoice alerts)."""
    rows = await session.scalars(
        select(User)
        .join(Contact, Contact.impower_id == User.contact_id_impower)
        .join(ContractContact, ContractContact.contact_id == Contact.id)
        .join(Contract, Contract.id == ContractContact.contract_id)
        .where(
            User.organization_id == organization_id,
            User.role.in_([UserRole.EIGENTUEMER, UserRole.BEIRAT]),
            User.deleted_at.is_(None),
            User.contact_id_impower.is_not(None),
            Contact.organization_id == organization_id,
            Contract.property_id == property_id,
            active_contract_filter(),
        )
        .distinct()
    )
    return list(rows.all())
