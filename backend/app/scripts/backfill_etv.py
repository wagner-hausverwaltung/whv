"""One-off: backfill EtvAssembly stubs from existing
OWNERS_MEETING_INVITATION documents (sourced from Impower).

Usage on staging:

    docker compose exec -T backend python -m app.scripts.backfill_etv
    docker compose exec -T backend python -m app.scripts.backfill_etv --extract
    docker compose exec -T backend python -m app.scripts.backfill_etv --reextract-all

`--extract` enqueues an `extract_etv_metadata` Celery task for each
newly-created assembly so the LLM (ADR-0008) fills in the actual
meeting date / location / Tagesordnung. Requires GEMINI_API_KEY in the
env and a running Celery worker; without either, the worker logs a
"skipped_provider_unavailable" audit row and moves on (the row is
still in place, just with the placeholder date — re-run once the
provider is configured).

`--reextract-all` is the catch-up flag: enqueue extraction for EVERY
existing assembly whose `auto_extracted_at` is NULL and `verified_at`
is NULL. Use this when the GEMINI_API_KEY wasn't set during the
initial `--extract` pass; the stubs are already in place from a
prior plain-backfill run, they just never got their LLM pass.
Verwalter-verified rows are never touched.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import EtvAssembly, Organization
from app.services.etv import backfill_assemblies_from_invitations


async def amain(*, extract: bool, reextract_all: bool) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, future=True)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    all_created_ids: list[uuid.UUID] = []
    backfill_ids: list[uuid.UUID] = []

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
            backfill_ids.extend(ids)
        await session.commit()

        # --reextract-all picks up every assembly that hasn't been
        # extracted AND hasn't been Verwalter-verified. Includes the
        # rows just inserted by this run as well as earlier
        # plain-backfill stubs from prior runs.
        if reextract_all:
            stmt = select(EtvAssembly.id).where(
                EtvAssembly.deleted_at.is_(None),
                EtvAssembly.auto_extracted_at.is_(None),
                EtvAssembly.verified_at.is_(None),
            )
            rows = (await session.execute(stmt)).all()
            all_created_ids = [r[0] for r in rows]
        else:
            all_created_ids = backfill_ids

    await engine.dispose()

    if extract or reextract_all:
        if not all_created_ids:
            print("--extract: nothing to enqueue.")
            return
        # Enqueue *after* the commit + engine dispose so workers find
        # the rows. `.delay()` pushes onto Redis; non-blocking.
        from app.workers.tasks import extract_etv_metadata

        for aid in all_created_ids:
            extract_etv_metadata.delay(str(aid))
        flag = "--reextract-all" if reextract_all else "--extract"
        print(
            f"{flag}: enqueued {len(all_created_ids)} extraction tasks "
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
    parser.add_argument(
        "--reextract-all",
        action="store_true",
        help=(
            "Enqueue extraction for EVERY existing assembly that hasn't "
            "been auto-extracted yet AND hasn't been Verwalter-verified. "
            "Use this when GEMINI_API_KEY wasn't set during the initial "
            "--extract pass."
        ),
    )
    args = parser.parse_args()
    asyncio.run(amain(extract=args.extract, reextract_all=args.reextract_all))


if __name__ == "__main__":
    main()
