"""Unit master-table enrichment.

The bare Unit row carries MEA / Fläche / Rooms (already on the
mirror), but the question every property-detail view actually asks
is "who's in this Einheit right now?" — and that's a join across
contracts + contract_contacts + contacts. This module bundles
the join behind `load_current_contracts_for_property` so the
property-detail endpoint stays cheap to read.

Active = the contract row is not soft-deleted AND today falls
within [start_date, end_date], where either bound may be NULL
(open-ended). We do NOT consult `is_vacant` — a vacant Mietvertrag
that still has a Mieter contact on it is mid-handover, surface it.

Returned dict: `{unit_id: [UnitContractSummary, …]}`. Empty when
the unit has no active contracts (vacant or stub property without
a contract mirror yet).
"""

import uuid
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Contact, ContactKind, Contract, ContractContact, Unit
from app.schemas.unit import UnitContractSummary


def _contact_label(contact: Contact) -> str:
    """Render the human-readable label the clients display.

    Person: "Dr. Max Mustermann" (title + name).
    Company: "Acme Hausverwaltung GmbH".
    Falls back to `recipient_name` (Impower's catch-all) or a
    dash so the UI never shows an empty contact chip.
    """
    if contact.kind == ContactKind.COMPANY:
        return (contact.company_name or contact.recipient_name or "—").strip()
    parts: list[str] = []
    if contact.title:
        parts.append(contact.title)
    if contact.first_name:
        parts.append(contact.first_name)
    if contact.last_name:
        parts.append(contact.last_name)
    if parts:
        return " ".join(parts)
    return (contact.recipient_name or "—").strip()


async def load_current_contracts_for_property(
    session: AsyncSession,
    *,
    property_id: uuid.UUID,
    today: date | None = None,
) -> dict[uuid.UUID, list[UnitContractSummary]]:
    """Single query (well, two: one for the contracts, one for the
    contacts that those contracts reference) bucketed by unit id.

    Bound by `property_id` so a Verwalter pulling a 5000-unit org
    doesn't accidentally scan every contract — we want O(units in
    this property) reads.
    """
    if today is None:
        today = date.today()

    # Step 1: active contracts on units belonging to this property.
    contract_stmt = select(Contract).where(
        Contract.property_id == property_id,
        Contract.unit_id.is_not(None),
        Contract.deleted_at.is_(None),
        or_(Contract.start_date.is_(None), Contract.start_date <= today),
        or_(Contract.end_date.is_(None), Contract.end_date >= today),
    )
    contracts = (await session.scalars(contract_stmt)).all()
    if not contracts:
        return {}

    # Step 2: junction rows so we can find the contacts. One query
    # for all contracts on this property — cheaper than per-contract.
    contract_ids = [c.id for c in contracts]
    junction_stmt = select(ContractContact).where(ContractContact.contract_id.in_(contract_ids))
    junctions = (await session.scalars(junction_stmt)).all()
    contact_ids = {j.contact_id for j in junctions}

    contacts_by_id: dict[uuid.UUID, Contact] = {}
    if contact_ids:
        contact_rows = (
            await session.scalars(
                select(Contact).where(
                    Contact.id.in_(contact_ids),
                    Contact.deleted_at.is_(None),
                )
            )
        ).all()
        contacts_by_id = {c.id: c for c in contact_rows}

    # Bucket junctions by contract for the per-row build.
    by_contract: dict[uuid.UUID, list[ContractContact]] = {}
    for j in junctions:
        by_contract.setdefault(j.contract_id, []).append(j)

    out: dict[uuid.UUID, list[UnitContractSummary]] = {}
    for c in contracts:
        if c.unit_id is None:
            continue
        # A contract can carry multiple contacts (joint owners,
        # tenants + co-tenants). Render one summary row per
        # (contract x contact) so the UI shows each name with
        # its role.
        cj = by_contract.get(c.id, [])
        if cj:
            for j in cj:
                contact = contacts_by_id.get(j.contact_id)
                summary = UnitContractSummary(
                    contract_id=c.id,
                    contract_number=c.contract_number,
                    type=c.type,
                    contact_id=j.contact_id,
                    contact_label=_contact_label(contact) if contact else None,
                    role=j.role,
                    start_date=c.start_date,
                    end_date=c.end_date,
                )
                out.setdefault(c.unit_id, []).append(summary)
        else:
            # Contract without contacts (rare; data hygiene issue)
            # — surface it so the Verwalter notices.
            summary = UnitContractSummary(
                contract_id=c.id,
                contract_number=c.contract_number,
                type=c.type,
                contact_id=None,
                contact_label=None,
                role=None,
                start_date=c.start_date,
                end_date=c.end_date,
            )
            out.setdefault(c.unit_id, []).append(summary)

    return out


async def attach_current_contracts_to_units(
    session: AsyncSession,
    *,
    units: list[Unit],
    property_id: uuid.UUID,
) -> dict[uuid.UUID, list[UnitContractSummary]]:
    """Convenience wrapper for the property-detail handler. Same
    signature returns the same dict — handler then mutates each
    UnitResponse.current_contracts after model_validate."""
    return await load_current_contracts_for_property(session, property_id=property_id)
