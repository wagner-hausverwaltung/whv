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
    sync_documents,
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
        choices=["properties", "units", "contacts", "contracts", "documents", "all"],
    )

    # Webhook lifecycle — register / list / delete Impower connections.
    # See app/api/v1/webhooks.py for the receiver; this CLI is the
    # "tell Impower to start delivering to us" side. One-time
    # operation per environment (re-run only when the URL or secret
    # changes).
    wh = sub.add_parser("webhook", help="Manage Impower webhook connections")
    wh_sub = wh.add_subparsers(dest="wh_cmd", required=True)
    reg = wh_sub.add_parser(
        "register",
        help="POST /v2/connections — subscribe Impower to deliver "
        "entity-change events to our /webhooks/impower endpoint.",
    )
    reg.add_argument(
        "--url",
        required=True,
        help="Public webhook URL (e.g. https://staging.api.wagner-hausverwaltung.com/webhooks/impower)",
    )
    reg.add_argument(
        "--secret",
        help="HMAC secret. Defaults to IMPOWER_WEBHOOK_SECRET from .env.",
    )
    reg.add_argument(
        "--name",
        default="WHV platform",
        help="Display name shown in the Impower admin UI.",
    )
    wh_sub.add_parser("list", help="List currently-registered connections.")
    rm = wh_sub.add_parser("delete", help="Delete a registered connection by id.")
    rm.add_argument("connection_id", type=int)

    args = parser.parse_args()

    settings = get_settings()
    if not settings.impower_api_token:
        raise SystemExit("IMPOWER_API_TOKEN is not set in .env")

    if args.cmd == "webhook":
        await _run_webhook(args, settings)
        return

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
        if args.entity in ("documents", "all"):
            await _run("documents", sync_documents, session, client)

    await engine.dispose()


async def _run_webhook(args: argparse.Namespace, settings: object) -> None:
    """Webhook-subcommand dispatcher. Separate from the sync flow so we
    don't open a DB session for what's purely an HTTP-to-Impower call."""
    import json as _json

    async with ImpowerClient(
        settings.impower_api_base,  # type: ignore[attr-defined]
        settings.impower_api_token,  # type: ignore[attr-defined]
    ) as client:
        if args.wh_cmd == "register":
            secret = args.secret or settings.impower_webhook_secret  # type: ignore[attr-defined]
            if not secret:
                raise SystemExit(
                    "IMPOWER_WEBHOOK_SECRET is not set in .env and no "
                    "--secret was supplied. The webhook receiver requires "
                    "this to verify HMAC signatures."
                )
            result = await client.register_connection(
                webhook_url=args.url,
                secret=secret,
                name=args.name,
            )
            print("Registered connection:", flush=True)
            print(_json.dumps(result, indent=2), flush=True)
        elif args.wh_cmd == "list":
            connections = await client.list_connections()
            print(f"{len(connections)} connection(s):", flush=True)
            for c in connections:
                print(_json.dumps(c, indent=2), flush=True)
        elif args.wh_cmd == "delete":
            await client.delete_connection(args.connection_id)
            print(f"Deleted connection {args.connection_id}", flush=True)


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
