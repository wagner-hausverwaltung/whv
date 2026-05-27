"""In-process TTL cache for the Impower invoice-detail fetch.

The Dienstleister dialog hits `/me/properties/{id}/invoices/{doc_id}`
which round-trips to Impower's `/v2/invoices/{id}` every time an
owner opens the dialog. Most invoices change rarely (a Verwalter
might tweak a booking line once a month) so a short TTL is enough
to absorb the "user clicks, looks, closes, re-opens 10 seconds
later" burst pattern.

Design notes:

* Keyed by `impower_invoice_id` (int) only — the data is identical
  regardless of which user requests it. Authorization happens at
  the endpoint layer BEFORE we touch the cache, so a Mieter on
  Unit 4 can't peek at an invoice they don't have access to just
  because some Verwalter populated it.
* Async-safe via a single asyncio.Lock around mutation paths.
  Reads are fine without locking because the dict op is atomic
  under the GIL.
* Single-process scope — when the API grows beyond one replica
  (post task #72 / push-notifications work) the right move is
  Redis, not bigger in-memory. This module's interface stays the
  same.
* TTL = 5 minutes. Verwalter who books an invoice in Impower and
  expects the owner to see it instantly should refresh by closing
  the dialog and waiting; the typical reconciliation lag is
  measured in hours anyway.

Cache shape: `{invoice_id: (expires_at_monotonic, payload_dict)}`.
We store the raw Impower dict (not InvoiceDetailResponse) so the
projection helper can run on every read — that way if we change
the projection in code, the cached payload still applies without
needing a cache flush.
"""

import asyncio
import time
from typing import Any

_DEFAULT_TTL_SECONDS = 300.0  # 5 min


class InvoiceCache:
    """Tiny TTL cache; one instance per process via `get_invoice_cache`."""

    def __init__(self, ttl_seconds: float = _DEFAULT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._store: dict[int, tuple[float, dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    def get(self, invoice_id: int) -> dict[str, Any] | None:
        """Return the cached payload if still fresh, else None. The
        `time.monotonic()` clock avoids wall-clock-jitter issues
        across NTP corrections."""
        entry = self._store.get(invoice_id)
        if entry is None:
            return None
        expires_at, payload = entry
        if time.monotonic() >= expires_at:
            # Lazy eviction. We don't bother with a background sweep
            # because the dict tops out at maybe a few hundred entries
            # per replica in realistic load (number of open dialogs
            # in any 5-min window).
            return None
        return payload

    async def set(self, invoice_id: int, payload: dict[str, Any]) -> None:
        async with self._lock:
            self._store[invoice_id] = (time.monotonic() + self._ttl, payload)

    async def invalidate(self, invoice_id: int) -> None:
        """Manual eviction — call this from any future write path
        that mutates an invoice (admin SPA edit, webhook from
        Impower). Currently unused; included so the wiring is
        obvious when the need arises."""
        async with self._lock:
            self._store.pop(invoice_id, None)

    async def clear(self) -> None:
        """Test hook — flush between fixture runs."""
        async with self._lock:
            self._store.clear()


# Single process-wide instance. FastAPI dependencies could pass this
# around via Depends, but the cache has no per-request state so a
# module-level singleton is simpler.
_INSTANCE: InvoiceCache | None = None


def get_invoice_cache() -> InvoiceCache:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = InvoiceCache()
    return _INSTANCE
