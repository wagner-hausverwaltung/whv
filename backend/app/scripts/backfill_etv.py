"""One-off: backfill EtvAssembly stubs from existing
OWNERS_MEETING_INVITATION documents (sourced from Impower).

Usage on staging:

    docker compose exec -T backend python -m app.scripts.backfill_etv

The service helper is idempotent — re-running is safe.
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import Organization
from app.services.etv import backfill_assemblies_from_invitations


async def amain() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, future=True)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as session:
        orgs = (await session.execute(select(Organization))).scalars().all()
        if not orgs:
            print("No organizations found — nothing to backfill.")
            return
        for org in orgs:
            org_id: uuid.UUID = org.id
            created, skipped = await backfill_assemblies_from_invitations(
                session, organization_id=org_id
            )
            print(
                f"org={org.name!r:40s} created={created:3d} skipped={skipped:3d}"
            )
        await session.commit()
    await engine.dispose()


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
