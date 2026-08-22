"""Fill properties.lat/lng from their postal address — one-off, idempotent.

The phone suggests the destination property from a trip's end position
("nächste WEG im Umkreis von 300 m"), which needs coordinates we never had.
Geocoding happens once here, server-side, rather than on every phone: it is
deterministic, reviewable, and Nominatim's usage policy (1 req/s, identify
yourself) is trivially met for a few dozen properties.

    .venv/bin/python scripts/geocode_properties.py            # only missing
    .venv/bin/python scripts/geocode_properties.py --dry-run  # print, don't write
    .venv/bin/python scripts/geocode_properties.py --force    # re-geocode all

Prod:  docker exec -e PYTHONPATH=/app -w /app whv-backend-1 python scripts/geocode_properties.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.models import Property

_NOMINATIM = "https://nominatim.openstreetmap.org/search"
_UA = "WHV-Fahrtenbuch/1.0 (info@wagner-hausverwaltung.com)"


def _address(p: Property) -> str | None:
    street = " ".join(x for x in (p.street, p.number) if x)
    city = " ".join(x for x in (p.postal_code, p.city) if x)
    if not street or not city:
        return None
    return f"{street}, {city}, {p.country or 'Deutschland'}"


async def _lookup(client: httpx.AsyncClient, query: str) -> tuple[Decimal, Decimal] | None:
    r = await client.get(
        _NOMINATIM,
        params={"q": query, "format": "json", "limit": 1, "countrycodes": "de"},
        headers={"User-Agent": _UA},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if not data:
        return None
    return Decimal(data[0]["lat"]).quantize(Decimal("0.000001")), Decimal(data[0]["lon"]).quantize(
        Decimal("0.000001")
    )


async def main(*, dry_run: bool, force: bool) -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    missing = 0
    try:
        async with sm() as session, httpx.AsyncClient() as client:
            stmt = select(Property).where(Property.deleted_at.is_(None)).order_by(Property.name)
            if not force:
                stmt = stmt.where(Property.lat.is_(None))
            props = (await session.scalars(stmt)).all()
            print(f"{len(props)} Objekte zu geokodieren")
            for p in props:
                q = _address(p)
                if q is None:
                    print(f"  SKIP {p.name}: Adresse unvollständig")
                    missing += 1
                    continue
                hit = await _lookup(client, q)
                if hit is None:
                    print(f"  MISS {p.name}: {q}")
                    missing += 1
                else:
                    lat, lng = hit
                    print(f"  OK   {p.name}: {lat}, {lng}")
                    if not dry_run:
                        p.lat, p.lng = lat, lng
                await asyncio.sleep(1.1)  # Nominatim: max 1 request per second
            if not dry_run:
                await session.commit()
    finally:
        await engine.dispose()
    print(f"fertig — {missing} ohne Koordinaten")
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(dry_run=args.dry_run, force=args.force)))
