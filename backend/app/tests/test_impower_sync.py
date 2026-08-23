from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import WHV_ORGANIZATION_ID
from app.integrations.impower.schemas import PropertyDto
from app.integrations.impower.sync import sync_properties
from app.models import Organization, Property, PropertyState, PropertyType


class _FakeClient:
    """Stub client that yields a fixed batch of properties."""

    def __init__(self, properties: list[dict[str, Any]]) -> None:
        self._properties = properties

    async def iter_properties(self) -> AsyncIterator[PropertyDto]:
        for p in self._properties:
            yield PropertyDto.model_validate(p)


async def _seed_whv_org(session: AsyncSession) -> None:
    # Conftest drops & recreates tables via metadata, so the migration's seed row is absent.
    # Re-create the singleton WHV organization that sync_* rows reference.
    if await session.scalar(select(Organization).where(Organization.id == WHV_ORGANIZATION_ID)):
        return
    session.add(Organization(id=WHV_ORGANIZATION_ID, name="Wagner Hausverwaltung GmbH"))
    await session.flush()


async def test_sync_properties_inserts_new_rows(session: AsyncSession) -> None:
    await _seed_whv_org(session)
    client = _FakeClient(
        [
            {
                "id": 1001,
                "name": "Schillerstraße 12",
                "type": "STRATA",
                "state": "READY",
                "propertyHrId": "WEG-001",
                "address": {
                    "city": "Stuttgart",
                    "street": "Schillerstraße",
                    "number": "12",
                    "postalCode": "70173",
                    "country": "DE",
                },
            },
            {
                "id": 1002,
                "name": "Waldmeisterweg 28",
                "type": "RENTAL",
                "state": "READY",
                "propertyHrId": "MV-002",
                "address": {"city": "Stuttgart", "street": "Waldmeisterweg", "number": "28"},
            },
        ]
    )
    stats = await sync_properties(session, client)  # type: ignore[arg-type]

    assert stats.fetched == 2
    assert stats.upserted == 2
    assert stats.skipped == 0

    # Filter to the synced rows by impower_id — other tests in the shared DB
    # may have committed Property rows without an impower_id.
    rows = (
        await session.scalars(
            select(Property)
            .where(Property.impower_id.in_([1001, 1002]))
            .order_by(Property.impower_id)
        )
    ).all()
    assert [r.impower_id for r in rows] == [1001, 1002]
    assert rows[0].type == PropertyType.STRATA
    assert rows[0].state == PropertyState.READY
    assert rows[0].city == "Stuttgart"
    assert rows[0].raw_jsonb is not None
    assert rows[0].raw_jsonb["id"] == 1001


async def test_sync_properties_updates_existing(session: AsyncSession) -> None:
    await _seed_whv_org(session)
    first_client = _FakeClient(
        [
            {
                "id": 2001,
                "name": "Initial Name",
                "type": "OWNER",
                "state": "DRAFT",
                "address": {"city": "Stuttgart"},
            }
        ]
    )
    await sync_properties(session, first_client)  # type: ignore[arg-type]

    second_client = _FakeClient(
        [
            {
                "id": 2001,
                "name": "Updated Name",
                "type": "OWNER",
                "state": "READY",
                "address": {"city": "Stuttgart", "street": "Königstraße"},
            }
        ]
    )
    stats = await sync_properties(session, second_client)  # type: ignore[arg-type]
    assert stats.upserted == 1

    row = await session.scalar(select(Property).where(Property.impower_id == 2001))
    assert row is not None
    assert row.name == "Updated Name"
    assert row.state == PropertyState.READY
    assert row.street == "Königstraße"


async def test_sync_skips_invalid_property(session: AsyncSession) -> None:
    await _seed_whv_org(session)
    # Missing required fields (no type, no state) → should be skipped, not raise.
    client = _FakeClient([{"id": 9001, "name": "broken"}])
    stats = await sync_properties(session, client)  # type: ignore[arg-type]
    assert stats.fetched == 1
    assert stats.upserted == 0
    assert stats.skipped == 1
    assert len(stats.warnings) == 1


async def test_sync_hides_handed_over_properties(session: AsyncSession) -> None:
    """Impower "Abgegeben" (DISABLED) soft-deletes the row — the one switch that
    hides it in app, portal, admin and CarPlay — and keeps the first hand-over
    timestamp; READY again clears it."""
    await _seed_whv_org(session)
    base: dict[str, Any] = {
        "id": 3001,
        "name": "MV Kornwestheimer Straße 59B",
        "type": "RENTAL",
        "address": {"city": "Stuttgart"},
    }
    await sync_properties(session, _FakeClient([{**base, "state": "READY"}]))  # type: ignore[arg-type]
    row = await session.scalar(select(Property).where(Property.impower_id == 3001))
    assert row is not None and row.deleted_at is None

    await sync_properties(session, _FakeClient([{**base, "state": "DISABLED"}]))  # type: ignore[arg-type]
    await session.refresh(row)
    assert row.state == PropertyState.DISABLED
    assert row.deleted_at is not None
    handed_over_at = row.deleted_at

    # A second sync while still handed over keeps the original timestamp.
    await sync_properties(session, _FakeClient([{**base, "state": "DISABLED"}]))
    await session.refresh(row)
    assert row.deleted_at == handed_over_at

    # Re-activated in Impower → visible again.
    await sync_properties(session, _FakeClient([{**base, "state": "READY"}]))
    await session.refresh(row)
    assert row.deleted_at is None
