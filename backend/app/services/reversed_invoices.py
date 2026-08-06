"""Which invoices are storniert (REVERSED), per property.

Owners must never see cancelled invoices in the Dienstleister view — a
storno is a bookkeeping correction, and showing it invites exactly the
question an owner asked in July 2026 ("this firm never invoiced us").
Roughly 6% of the mirrored invoice documents are in this state.

The state is NOT in our mirror. `documents.state` is Impower's document
lifecycle (READY / FAILED / …); the invoice state is a separate enum
(DRAFT / READY / BOOKED / SCHEDULED / REVERSED) that only the invoice
resource carries, and we deliberately don't mirror invoices locally
(see `app.schemas.invoice` — too high a churn rate). So we ask Impower,
server-side-filtered to the cancelled ones only: one small request per
property instead of one per invoice.

Availability over freshness: the last successful answer is kept and
only ever REPLACED by another success. A TTL decides when to refetch,
not when to forget. So an Impower outage degrades to slightly stale
filtering rather than to showing storno invoices again — only a cold
process that has never reached Impower falls back to unfiltered, and
that logs a warning.
"""

import asyncio
import logging
import time

from app.config import Settings

logger = logging.getLogger(__name__)

# Long enough to absorb a browsing session, short enough that a storno
# booked in Impower disappears from the owner view within minutes.
_DEFAULT_TTL_SECONDS = 300.0
# After a failed lookup, wait this long before trying Impower again.
# Without it an outage makes EVERY vendor-tab request pay the full
# Impower timeout, turning a degraded dependency into a slow page.
_RETRY_AFTER_FAILURE_SECONDS = 30.0


class ReversedInvoiceCache:
    """Per-property set of REVERSED invoice ids, with a refetch TTL."""

    def __init__(self, ttl_seconds: float = _DEFAULT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        # property impower id -> (refetch_after_monotonic, ids)
        self._store: dict[int, tuple[float, set[int]]] = {}
        self._lock = asyncio.Lock()

    async def get(self, impower_property_id: int, settings: Settings) -> set[int]:
        """Cancelled invoice ids for the property.

        Returns an empty set when Impower is unreachable and nothing was
        ever cached — the caller then shows the unfiltered list, which is
        the pre-existing behaviour rather than a broken tab.
        """
        entry = self._store.get(impower_property_id)
        if entry is not None and time.monotonic() < entry[0]:
            return entry[1]

        if not settings.impower_api_token:
            return entry[1] if entry else set()

        from app.integrations.impower.client import ImpowerClient

        try:
            async with ImpowerClient(
                settings.impower_api_base, settings.impower_api_token
            ) as client:
                ids = await client.list_reversed_invoice_ids(impower_property_id)
        except Exception:
            # Back off before the next attempt, keeping whatever answer we
            # already had. The previous set is preserved — it is only ever
            # replaced by a successful lookup, never dropped on error.
            previous = entry[1] if entry is not None else set()
            async with self._lock:
                self._store[impower_property_id] = (
                    time.monotonic() + _RETRY_AFTER_FAILURE_SECONDS,
                    previous,
                )
            if entry is not None:
                logger.warning(
                    "storno lookup failed for property %s — serving the last known set",
                    impower_property_id,
                    exc_info=True,
                )
            else:
                # The one case where cancelled invoices reappear for owners.
                logger.warning(
                    "storno lookup failed for property %s and nothing cached — "
                    "cancelled invoices may be visible to owners",
                    impower_property_id,
                    exc_info=True,
                )
            return previous

        async with self._lock:
            self._store[impower_property_id] = (time.monotonic() + self._ttl, ids)
        return ids

    async def clear(self) -> None:
        """Test hook — flush between fixture runs."""
        async with self._lock:
            self._store.clear()


_INSTANCE: ReversedInvoiceCache | None = None


def get_reversed_invoice_cache() -> ReversedInvoiceCache:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ReversedInvoiceCache()
    return _INSTANCE
