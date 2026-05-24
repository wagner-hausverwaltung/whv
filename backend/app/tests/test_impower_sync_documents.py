from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.constants import WHV_ORGANIZATION_ID
from app.integrations.impower.schemas import DocumentDto
from app.integrations.impower.sync import (
    _map_document_kind,
    _map_document_state,
    sync_documents,
)
from app.models import Document, DocumentKind, DocumentState, Organization, Property


class _FakeClient:
    """Yields docs whose `propertyId` matches the requested filter.

    sync_documents iterates over every locally-known property's impower_id and
    calls iter_documents(property_id=X); this stub mirrors Impower's filtering
    so each doc surfaces exactly once.
    """

    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    async def iter_documents(self, property_id: int) -> AsyncIterator[DocumentDto]:
        for d in self._docs:
            if d.get("propertyId") == property_id:
                yield DocumentDto.model_validate(d)


async def _seed_whv_org_and_property(session: AsyncSession, impower_id: int) -> Property:
    """Idempotent seed of the WHV org + a property with the given impower_id."""
    if not await session.scalar(select(Organization).where(Organization.id == WHV_ORGANIZATION_ID)):
        session.add(Organization(id=WHV_ORGANIZATION_ID, name="WHV"))
        await session.flush()
    existing = await session.scalar(select(Property).where(Property.impower_id == impower_id))
    if existing is not None:
        return existing
    prop = Property(
        organization_id=WHV_ORGANIZATION_ID,
        impower_id=impower_id,
        name=f"Test property {impower_id}",
        type="STRATA",
        state="READY",
    )
    session.add(prop)
    await session.flush()
    return prop


def test_map_document_kind_known_values() -> None:
    assert _map_document_kind("HOUSE_MONEY_SETTLEMENT") == DocumentKind.JAHRESABRECHNUNG
    assert _map_document_kind("ECONOMIC_PLAN") == DocumentKind.WIRTSCHAFTSPLAN
    assert _map_document_kind("OWNERS_MEETING_PROTOCOL") == DocumentKind.PROTOKOLL
    assert _map_document_kind("INVOICE") == DocumentKind.RECHNUNG
    assert _map_document_kind("INVOICE_XML") == DocumentKind.RECHNUNG


def test_map_document_kind_unknown_falls_through_to_sonstiges() -> None:
    assert _map_document_kind("DATEV_DEBTOR_CREDITOR") == DocumentKind.SONSTIGES
    assert _map_document_kind("OTHER") == DocumentKind.SONSTIGES
    assert _map_document_kind(None) == DocumentKind.SONSTIGES
    assert _map_document_kind("MADE_UP_VALUE") == DocumentKind.SONSTIGES


def test_map_document_state_known_values() -> None:
    assert _map_document_state("READY") == DocumentState.READY
    assert _map_document_state("DRAFT") == DocumentState.DRAFT
    assert _map_document_state(None) is None
    assert _map_document_state("MADE_UP_STATE") is None


async def test_sync_documents_upserts_metadata(test_engine: AsyncEngine) -> None:
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as session:
        prop = await _seed_whv_org_and_property(session, impower_id=753867)
        await session.commit()

        client = _FakeClient(
            [
                {
                    "id": 8001,
                    "name": "Jahresabrechnung 2024.pdf",
                    "sourceType": "HOUSE_MONEY_SETTLEMENT",
                    "state": "READY",
                    "propertyId": 753867,
                    "amount": 12345.67,
                    "issuedDate": "2024-12-31",
                },
                {
                    "id": 8002,
                    "name": "Rechnung Klempnerei.pdf",
                    "sourceType": "INVOICE",
                    "state": "READY",
                    "propertyId": 753867,
                    "amount": 250.0,
                    "issuedDate": "2024-09-15",
                },
            ]
        )
        stats = await sync_documents(session, client)  # type: ignore[arg-type]

    assert stats.fetched == 2
    assert stats.upserted == 2
    assert stats.skipped == 0

    async with sm() as session:
        rows = (await session.scalars(select(Document).order_by(Document.impower_id))).all()
        assert [r.impower_id for r in rows] == [8001, 8002]
        assert rows[0].kind == DocumentKind.JAHRESABRECHNUNG
        assert rows[0].impower_source_type == "HOUSE_MONEY_SETTLEMENT"
        assert rows[0].property_id == prop.id
        assert rows[0].state == DocumentState.READY
        assert rows[1].kind == DocumentKind.RECHNUNG


async def test_sync_documents_updates_on_rerun(test_engine: AsyncEngine) -> None:
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as session:
        await _seed_whv_org_and_property(session, impower_id=754000)
        await session.commit()

        first = _FakeClient(
            [
                {
                    "id": 8101,
                    "name": "Original name.pdf",
                    "sourceType": "HOUSE_MONEY_SETTLEMENT",
                    "state": "DRAFT",
                    "propertyId": 754000,
                }
            ]
        )
        await sync_documents(session, first)  # type: ignore[arg-type]

    async with sm() as session:
        second = _FakeClient(
            [
                {
                    "id": 8101,
                    "name": "Updated name.pdf",
                    "sourceType": "HOUSE_MONEY_SETTLEMENT",
                    "state": "READY",
                    "propertyId": 754000,
                }
            ]
        )
        stats = await sync_documents(session, second)  # type: ignore[arg-type]
        assert stats.upserted == 1

    async with sm() as session:
        row = await session.scalar(select(Document).where(Document.impower_id == 8101))
        assert row is not None
        assert row.name == "Updated name.pdf"
        assert row.state == DocumentState.READY


async def test_sync_documents_nulls_unknown_secondary_fks(test_engine: AsyncEngine) -> None:
    """propertyId always matches (we only call iter_documents for known properties), but
    contractId/unitId/contactId may reference Impower IDs we haven't synced — those
    should resolve to NULL FKs rather than raise.
    """
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as session:
        prop = await _seed_whv_org_and_property(session, impower_id=754001)
        await session.commit()

        client = _FakeClient(
            [
                {
                    "id": 8201,
                    "name": "OrphanFKs.pdf",
                    "sourceType": "OTHER",
                    "state": "READY",
                    "propertyId": 754001,
                    "contractId": 99999,  # not in local mirror
                    "unitId": 99998,  # not in local mirror
                    "contactId": 99997,  # not in local mirror
                }
            ]
        )
        stats = await sync_documents(session, client)  # type: ignore[arg-type]

    assert stats.upserted == 1
    async with sm() as session:
        row = await session.scalar(select(Document).where(Document.impower_id == 8201))
        assert row is not None
        assert row.property_id == prop.id
        assert row.contract_id is None
        assert row.unit_id is None
        assert row.contact_id is None


async def test_sync_documents_skips_invalid(test_engine: AsyncEngine) -> None:
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as session:
        await _seed_whv_org_and_property(session, impower_id=754002)
        await session.commit()

        # name missing → fetched then skipped
        client = _FakeClient(
            [{"id": 8301, "propertyId": 754002, "sourceType": "OTHER", "state": "READY"}]
        )
        stats = await sync_documents(session, client)  # type: ignore[arg-type]
        assert stats.fetched == 1
        assert stats.skipped == 1
        assert stats.upserted == 0
