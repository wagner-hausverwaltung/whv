from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import WHV_ORGANIZATION_ID
from app.integrations.impower.client import ImpowerClient
from app.integrations.impower.schemas import (
    ContactDto,
    ContractDto,
    DocumentDto,
    PropertyDto,
    UnitDto,
)
from app.models import (
    Building,
    Contact,
    ContactKind,
    Contract,
    ContractContact,
    Document,
    DocumentKind,
    DocumentState,
    Property,
    Unit,
)
from app.models._mixins import uuid7_pk

# Best-effort mapping from Impower's 31-value sourceType enum to our small
# DocumentKind enum. Values not listed fall through to SONSTIGES (catch-all).
# Raw sourceType is retained on `documents.impower_source_type` for traceability.
_IMPOWER_SOURCE_TYPE_TO_KIND: dict[str, DocumentKind] = {
    "HOUSE_MONEY_SETTLEMENT": DocumentKind.JAHRESABRECHNUNG,
    "ECONOMIC_PLAN": DocumentKind.WIRTSCHAFTSPLAN,
    "OWNERS_MEETING_PROTOCOL": DocumentKind.PROTOKOLL,
    "INVOICE": DocumentKind.RECHNUNG,
    "INVOICE_XML": DocumentKind.RECHNUNG,
    "OPS_COST_REPORT": DocumentKind.JAHRESABRECHNUNG,
    "RENT_SETTLEMENT_EXCHANGE": DocumentKind.JAHRESABRECHNUNG,
    "HEATING_COST_DISTRIBUTION": DocumentKind.JAHRESABRECHNUNG,
}


def _map_document_kind(source_type: str | None) -> DocumentKind:
    if source_type is None:
        return DocumentKind.SONSTIGES
    return _IMPOWER_SOURCE_TYPE_TO_KIND.get(source_type, DocumentKind.SONSTIGES)


def _map_document_state(state: str | None) -> DocumentState | None:
    if state is None:
        return None
    try:
        return DocumentState(state)
    except ValueError:
        return None


async def _iter_all_docs(
    client: ImpowerClient, property_impower_ids: list[int]
) -> "AsyncIterator[DocumentDto]":
    for prop_impower_id in property_impower_ids:
        async for doc in client.iter_documents(property_id=prop_impower_id):
            yield doc


@dataclass
class SyncStats:
    fetched: int = 0
    upserted: int = 0
    skipped: int = 0
    junctions: int = 0
    warnings: list[str] = field(default_factory=list)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _serialize(dto: Any) -> dict[str, Any]:
    result: dict[str, Any] = dto.model_dump(mode="json", exclude_none=False)
    return result


async def sync_properties(session: AsyncSession, client: ImpowerClient) -> SyncStats:
    stats = SyncStats()
    now = datetime.now(UTC)
    async for prop in client.iter_properties():
        stats.fetched += 1
        if prop.id is None or prop.type is None or prop.state is None or prop.name is None:
            stats.skipped += 1
            stats.warnings.append(f"property impower_id={prop.id} missing required fields")
            continue
        addr = prop.address
        values = {
            "id": uuid7_pk(),
            "organization_id": WHV_ORGANIZATION_ID,
            "impower_id": prop.id,
            "property_hr_id": prop.propertyHrId,
            "name": prop.name,
            "type": prop.type.value,
            "state": prop.state.value,
            "city": addr.city if addr else None,
            "street": addr.street if addr else None,
            "number": addr.number if addr else None,
            "postal_code": addr.postalCode if addr else None,
            "country": addr.country if addr else None,
            "raw_jsonb": _serialize(prop),
            "last_synced_at": now,
        }
        update_set = {
            k: v for k, v in values.items() if k not in ("id", "organization_id", "impower_id")
        }
        update_set["updated_at"] = now
        stmt = (
            pg_insert(Property)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["impower_id"],
                set_=update_set,
            )
        )
        await session.execute(stmt)
        stats.upserted += 1
    await session.commit()
    return stats


async def sync_units(session: AsyncSession, client: ImpowerClient) -> SyncStats:
    stats = SyncStats()
    now = datetime.now(UTC)

    property_ids = {
        row.impower_id: row.id
        for row in (await session.execute(select(Property.id, Property.impower_id))).all()
    }

    async for unit in client.iter_units():
        stats.fetched += 1
        if unit.id is None or unit.type is None:
            stats.skipped += 1
            stats.warnings.append(f"unit impower_id={unit.id} missing required fields")
            continue
        impower_property_id = unit.propertyId
        if impower_property_id is None or impower_property_id not in property_ids:
            stats.skipped += 1
            stats.warnings.append(
                f"unit impower_id={unit.id} references unknown property "
                f"{impower_property_id}; sync properties first"
            )
            continue
        values = {
            "id": uuid7_pk(),
            "organization_id": WHV_ORGANIZATION_ID,
            "impower_id": unit.id,
            "property_id": property_ids[impower_property_id],
            "unit_hr_id": unit.unitHrId,
            "type": unit.type.value,
            "floor": unit.floor,
            "position": unit.position,
            "unit_rank": unit.unitRank,
            "is_owned_by_weg": unit.isOwnedByWeg,
            "raw_jsonb": _serialize(unit),
            "last_synced_at": now,
        }
        update_set = {
            k: v for k, v in values.items() if k not in ("id", "organization_id", "impower_id")
        }
        update_set["updated_at"] = now
        stmt = (
            pg_insert(Unit)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["impower_id"],
                set_=update_set,
            )
        )
        await session.execute(stmt)
        stats.upserted += 1
    await session.commit()
    return stats


async def sync_contacts(session: AsyncSession, client: ImpowerClient) -> SyncStats:
    stats = SyncStats()
    now = datetime.now(UTC)
    async for c in client.iter_contacts():
        stats.fetched += 1
        if c.id is None:
            stats.skipped += 1
            continue
        kind = ContactKind.COMPANY if c.companyName else ContactKind.PERSON
        details = c.details
        additional: dict[str, Any] = {}
        primary_email: str | None = None
        primary_phone: str | None = None
        date_of_birth: date | None = None
        vat_id: str | None = None
        trade_register_number: str | None = None
        mandate_number: str | None = None
        if details is not None:
            if details.email:
                primary_email = details.email[0]
                if len(details.email) > 1:
                    additional["emails_extra"] = details.email[1:]
            phones = (
                (details.mobilePhoneNumber or [])
                + (details.privatePhoneNumber or [])
                + (details.businessPhoneNumber or [])
            )
            if phones:
                primary_phone = phones[0]
                if len(phones) > 1:
                    additional["phones_extra"] = phones[1:]
            if details.fax:
                additional["fax"] = details.fax
            if details.website:
                additional["website"] = details.website
            date_of_birth = _parse_date(details.dateOfBirth)
            vat_id = details.vatId
            trade_register_number = details.tradeRegisterNumber
            mandate_number = details.mandateNumber

        values = {
            "id": uuid7_pk(),
            "organization_id": WHV_ORGANIZATION_ID,
            "impower_id": c.id,
            "kind": kind.value,
            "salutation": c.salutation,
            "title": c.title,
            "first_name": c.firstName,
            "last_name": c.lastName,
            "date_of_birth": date_of_birth,
            "company_name": c.companyName,
            "vat_id": vat_id,
            "trade_register_number": trade_register_number,
            "recipient_name": c.recipientName,
            "mandate_number": mandate_number,
            "email": primary_email,
            "phone": primary_phone,
            "additional_contacts": additional or None,
            "city": c.city,
            "street": c.street,
            "number": c.number,
            "postal_code": c.postalCode,
            "country": c.country,
            "raw_jsonb": _serialize(c),
            "last_synced_at": now,
        }
        update_set = {
            k: v for k, v in values.items() if k not in ("id", "organization_id", "impower_id")
        }
        update_set["updated_at"] = now
        stmt = (
            pg_insert(Contact)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["impower_id"],
                set_=update_set,
            )
        )
        await session.execute(stmt)
        stats.upserted += 1
    await session.commit()
    return stats


async def sync_contracts(session: AsyncSession, client: ImpowerClient) -> SyncStats:
    stats = SyncStats()
    now = datetime.now(UTC)

    property_ids = {
        row.impower_id: row.id
        for row in (await session.execute(select(Property.id, Property.impower_id))).all()
    }
    unit_ids = {
        row.impower_id: row.id
        for row in (await session.execute(select(Unit.id, Unit.impower_id))).all()
    }
    contact_ids = {
        row.impower_id: row.id
        for row in (await session.execute(select(Contact.id, Contact.impower_id))).all()
    }

    async for ct in client.iter_contracts():
        stats.fetched += 1
        if ct.id is None or ct.type is None:
            stats.skipped += 1
            continue
        impower_property_id = ct.propertyId
        if impower_property_id is None or impower_property_id not in property_ids:
            stats.skipped += 1
            stats.warnings.append(
                f"contract impower_id={ct.id} references unknown property {impower_property_id}"
            )
            continue
        our_property_id = property_ids[impower_property_id]
        our_unit_id = unit_ids.get(ct.unitId) if ct.unitId is not None else None

        values = {
            "id": uuid7_pk(),
            "organization_id": WHV_ORGANIZATION_ID,
            "impower_id": ct.id,
            "property_id": our_property_id,
            "unit_id": our_unit_id,
            "type": ct.type.value,
            "contract_number": ct.contractNumber,
            "name": ct.name,
            "start_date": _parse_date(ct.startDate),
            "end_date": _parse_date(ct.endDate),
            "is_vacant": ct.isVacant,
            "raw_jsonb": _serialize(ct),
            "last_synced_at": now,
        }
        update_set = {
            k: v for k, v in values.items() if k not in ("id", "organization_id", "impower_id")
        }
        update_set["updated_at"] = now
        stmt = (
            pg_insert(Contract)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["impower_id"],
                set_=update_set,
            )
            .returning(Contract.id)
        )
        result = await session.execute(stmt)
        our_contract_id = result.scalar_one()
        stats.upserted += 1

        # Rebuild junction rows for this contract from the Impower contacts[] array.
        await session.execute(
            delete(ContractContact).where(ContractContact.contract_id == our_contract_id)
        )
        for ref in ct.contacts or []:
            if ref.id is None or ref.id not in contact_ids:
                stats.warnings.append(
                    f"contract impower_id={ct.id} references unknown contact {ref.id}"
                )
                continue
            await session.execute(
                pg_insert(ContractContact).values(
                    contract_id=our_contract_id,
                    contact_id=contact_ids[ref.id],
                    role=None,
                )
            )
            stats.junctions += 1

    await session.commit()
    return stats


async def sync_documents(session: AsyncSession, client: ImpowerClient) -> SyncStats:
    """Sync documents per property.

    Impower's /v2/documents requires propertyId — calling it unfiltered times out.
    We iterate every known property's impower_id and pull its documents.
    """
    stats = SyncStats()
    now = datetime.now(UTC)

    property_ids = {
        row.impower_id: row.id
        for row in (await session.execute(select(Property.id, Property.impower_id))).all()
        if row.impower_id is not None
    }
    building_ids = {
        row.impower_id: row.id
        for row in (await session.execute(select(Building.id, Building.impower_id))).all()
    }
    unit_ids = {
        row.impower_id: row.id
        for row in (await session.execute(select(Unit.id, Unit.impower_id))).all()
    }
    contract_ids = {
        row.impower_id: row.id
        for row in (await session.execute(select(Contract.id, Contract.impower_id))).all()
    }
    contact_ids = {
        row.impower_id: row.id
        for row in (await session.execute(select(Contact.id, Contact.impower_id))).all()
    }

    docs_iter = _iter_all_docs(client, list(property_ids.keys()))
    async for doc in docs_iter:
        stats.fetched += 1
        if doc.id is None or doc.name is None:
            stats.skipped += 1
            stats.warnings.append(f"document impower_id={doc.id} missing required fields")
            continue

        kind = _map_document_kind(doc.sourceType)
        state = _map_document_state(doc.state)

        values: dict[str, Any] = {
            "id": uuid7_pk(),
            "organization_id": WHV_ORGANIZATION_ID,
            "impower_id": doc.id,
            "property_id": property_ids.get(doc.propertyId) if doc.propertyId is not None else None,
            "building_id": building_ids.get(doc.buildingId) if doc.buildingId is not None else None,
            "unit_id": unit_ids.get(doc.unitId) if doc.unitId is not None else None,
            "contract_id": contract_ids.get(doc.contractId) if doc.contractId is not None else None,
            "contact_id": contact_ids.get(doc.contactId) if doc.contactId is not None else None,
            "name": doc.name,
            "kind": kind.value,
            "impower_source_type": doc.sourceType,
            "amount": Decimal(str(doc.amount)) if doc.amount is not None else None,
            "issued_date": _parse_date(doc.issuedDate),
            "state": state.value if state is not None else None,
            "raw_jsonb": _serialize(doc),
            "last_synced_at": now,
        }
        update_set = {
            k: v for k, v in values.items() if k not in ("id", "organization_id", "impower_id")
        }
        update_set["updated_at"] = now
        stmt = (
            pg_insert(Document)
            .values(**values)
            .on_conflict_do_update(index_elements=["impower_id"], set_=update_set)
        )
        await session.execute(stmt)
        stats.upserted += 1
    await session.commit()
    return stats


# Silence ruff about an unused import (kept for forward use / type hints in tests).
_ = (ContactDto, ContractDto, DocumentDto, PropertyDto, UnitDto, Decimal)
