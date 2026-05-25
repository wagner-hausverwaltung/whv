"""One-off: backfill EtvAssembly stubs from existing
OWNERS_MEETING_INVITATION documents (sourced from Impower).

Usage on staging:

    docker compose exec -T backend python -m app.scripts.backfill_etv
    docker compose exec -T backend python -m app.scripts.backfill_etv --extract

`--extract` additionally enqueues an `extract_etv_metadata` Celery
task for each newly-created assembly so the LLM (ADR-0008) fills in
the actual meeting date / location / Tagesordnung. Requires
GEMINI_API_KEY in the env and a running Celery worker; without
either, the worker logs a "skipped_provider_unavailable" audit row
and moves on (the row is still in place, just with the placeholder
date — re-run with --extract once the provider is configured).
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import Organization
from app.services.etv import backfill_assemblies_from_invitations


async def amain(*, extract: bool) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, future=True)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    all_created_ids: list[uuid.UUID] = []
    async with sm() as session:
        orgs = (await session.execute(select(Organization))).scalars().all()
        if not orgs:
            print("No organizations found — nothing to backfill.")
            return
        for org in orgs:
            org_id: uuid.UUID = org.id
            created, skipped, ids = await backfill_assemblies_from_invitations(
                session, organization_id=org_id
            )
            print(
                f"org={org.name!r:40s} created={created:3d} skipped={skipped:3d}"
            )
            all_created_ids.extend(ids)
        await session.commit()
    await engine.dispose()

    if extract:
        if not all_created_ids:
            print(
                "--extract: nothing to enqueue (backfill produced 0 new rows). "
                "Re-run extraction on existing rows via "
                "`python -m app.scripts.backfill_etv --reextract-all` "
                "if you want to overwrite them."
            )
            return
        # Enqueue *after* the commit so workers can see the rows. The
        # Celery .delay() call itself doesn't block on the worker; it
        # just pushes onto the Redis queue.
        from app.workers.tasks import extract_etv_metadata

        for aid in all_created_ids:
            extract_etv_metadata.delay(str(aid))
        print(
            f"--extract: enqueued {len(all_created_ids)} extraction tasks "
            f"on the 'celery' queue."
        )


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.scripts.backfill_etv")
    parser.add_argument(
        "--extract",
        action="store_true",
        help=(
            "Also enqueue an LLM extraction task (ADR-0008) for each "
            "newly-created assembly. Requires GEMINI_API_KEY + a running "
            "Celery worker."
        ),
    )
    args = parser.parse_args()
    asyncio.run(amain(extract=args.extract))


if __name__ == "__main__":
    main()
