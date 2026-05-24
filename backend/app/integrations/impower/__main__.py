import argparse
import asyncio
import time
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.integrations.impower.client import ImpowerClient
from app.integrations.impower.sync import (
    SyncStats,
    sync_contacts,
    sync_contracts,
    sync_properties,
    sync_units,
)

_SyncFn = Callable[[AsyncSession, ImpowerClient], Awaitable[SyncStats]]


async def _run(name: str, fn: _SyncFn, session: AsyncSession, client: ImpowerClient) -> None:
    print(f"=== {name} ===", flush=True)
    start = time.perf_counter()
    stats = await fn(session, client)
    elapsed = time.perf_counter() - start
    print(
        f"  fetched={stats.fetched} upserted={stats.upserted} "
        f"skipped={stats.skipped} junctions={stats.junctions} ({elapsed:.2f}s)"
    )
    for w in stats.warnings[:10]:
        print(f"    warn: {w}")
    if len(stats.warnings) > 10:
        print(f"    ... and {len(stats.warnings) - 10} more warnings")


async def amain() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.integrations.impower")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sync_p = sub.add_parser(
        "sync", help="Pull master data from Impower and upsert into the local DB."
    )
    sync_p.add_argument(
        "entity",
        choices=["properties", "units", "contacts", "contracts", "all"],
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.impower_api_token:
        raise SystemExit("IMPOWER_API_TOKEN is not set in .env")

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with (
        ImpowerClient(settings.impower_api_base, settings.impower_api_token) as client,
        session_factory() as session,
    ):
        if args.entity in ("properties", "all"):
            await _run("properties", sync_properties, session, client)
        if args.entity in ("units", "all"):
            await _run("units", sync_units, session, client)
        if args.entity in ("contacts", "all"):
            await _run("contacts", sync_contacts, session, client)
        if args.entity in ("contracts", "all"):
            await _run("contracts", sync_contracts, session, client)

    await engine.dispose()


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
