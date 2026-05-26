"""Daily drift detector between the local mirror and Impower.

Counts live (non-soft-deleted) rows on our side for each mirrored
entity, counts rows on Impower's side via the iter_* helpers, and
diffs the two. A "drift" past the threshold logs a warning + sends
a Sentry message so we hear about it before owners notice stale
data in the portal.

Why a separate task rather than instrumenting the nightly sync:
the sync's job is to *resolve* drift by upserting. Reconciliation
is a watchdog — it answers "did the resolver leave anything
behind?" without writing. Failures in one shouldn't mask the
other.

The cost is real: counting Impower-side via the existing Slice/
Page iter_* helpers re-pages everything. Cheaper than a full
re-sync (no row marshalling) but not free. Daily cadence is the
right granularity.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.impower.client import ImpowerClient
from app.models import Contact, Contract, Document, Property, Unit

logger = logging.getLogger(__name__)

# Absolute + relative thresholds together so the alert fires both
# for "1 row missing in a 3-property tenant" (catches small fleets)
# AND "50 rows missing in a 5,000-row fleet" (catches big fleets).
# An "alert" is fired when EITHER is exceeded.
_ABS_DRIFT_ROWS = 5
_REL_DRIFT_PCT = 1.0  # 1% relative drift


@dataclass(frozen=True)
class ReconcileDiff:
    entity: str
    mirror_count: int
    impower_count: int

    @property
    def diff(self) -> int:
        return self.mirror_count - self.impower_count

    @property
    def is_drifted(self) -> bool:
        if abs(self.diff) >= _ABS_DRIFT_ROWS:
            return True
        denom = max(self.mirror_count, self.impower_count, 1)
        return (abs(self.diff) / denom) * 100 >= _REL_DRIFT_PCT


async def _count_mirror(session: AsyncSession) -> dict[str, int]:
    """One round-trip per entity counting non-soft-deleted rows."""
    out: dict[str, int] = {}
    out["properties"] = await session.scalar(
        select(func.count(Property.id)).where(Property.deleted_at.is_(None))
    ) or 0
    out["units"] = await session.scalar(
        select(func.count(Unit.id)).where(Unit.deleted_at.is_(None))
    ) or 0
    out["contracts"] = await session.scalar(
        select(func.count(Contract.id)).where(Contract.deleted_at.is_(None))
    ) or 0
    out["contacts"] = await session.scalar(
        select(func.count(Contact.id)).where(Contact.deleted_at.is_(None))
    ) or 0
    out["documents"] = await session.scalar(
        select(func.count(Document.id)).where(Document.deleted_at.is_(None))
    ) or 0
    return out


async def _count_impower(client: ImpowerClient) -> dict[str, int]:
    """Count live rows on Impower by iterating each entity type.

    Properties / contracts / contacts use Slice DTOs (no
    totalElements field) so we just walk + count. Units / documents
    use Page DTOs but we walk anyway for symmetry — at our scale
    (≤5k rows per entity) a few extra pages is fine.

    Documents are counted per-property because Impower's
    /v2/documents endpoint *requires* a propertyId filter. We
    accumulate across the property list we just counted.
    """
    out: dict[str, int] = {}

    out["properties"] = 0
    property_ids: list[int] = []
    async for p in client.iter_properties():
        out["properties"] += 1
        if p.id is not None:
            property_ids.append(p.id)

    out["units"] = 0
    async for _ in client.iter_units():
        out["units"] += 1

    out["contracts"] = 0
    async for _ in client.iter_contracts():
        out["contracts"] += 1

    out["contacts"] = 0
    async for _ in client.iter_contacts():
        out["contacts"] += 1

    out["documents"] = 0
    for pid in property_ids:
        async for _ in client.iter_documents(pid):
            out["documents"] += 1

    return out


async def reconcile(session: AsyncSession, client: ImpowerClient) -> list[ReconcileDiff]:
    """Run a full reconciliation pass. Returns one row per entity.

    Caller logs the result + alerts; this fn is side-effect free
    so it's straightforward to drive from tests and from the
    Celery task.
    """
    mirror = await _count_mirror(session)
    impower = await _count_impower(client)
    entities = sorted(set(mirror) | set(impower))
    return [
        ReconcileDiff(
            entity=e,
            mirror_count=mirror.get(e, 0),
            impower_count=impower.get(e, 0),
        )
        for e in entities
    ]


def alert_on_drift(diffs: list[ReconcileDiff]) -> None:
    """Log + Sentry-emit anything past the drift thresholds.

    Sentry import is lazy because sentry_sdk is only configured in
    prod / staging; the local dev `pytest` doesn't have it on the
    path. Falling back to a plain warning log when Sentry isn't
    initialised is the right behaviour.
    """
    drifted = [d for d in diffs if d.is_drifted]
    if not drifted:
        logger.info("impower reconcile: no drift")
        return

    summary = ", ".join(
        f"{d.entity}: mirror={d.mirror_count} impower={d.impower_count} diff={d.diff}"
        for d in drifted
    )
    logger.warning("impower reconcile drift: %s", summary)
    # Sentry import gated so the unit test (no sentry_sdk on the path)
    # still passes. Mypy gets `ignore[import-not-found]` for the same
    # reason. In prod the binary ships with sentry_sdk wired up.
    try:
        import sentry_sdk  # type: ignore[import-not-found]
    except ImportError:
        return
    sentry_sdk.capture_message(
        f"Impower mirror drift: {summary}",
        level="warning",
    )
