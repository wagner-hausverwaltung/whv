"""Fail when the alembic-migrated schema drifts from the SQLAlchemy models.

Why: tests build tables from `Base.metadata`, prod builds them from the
migrations. The two silently diverged once (trips.created_at without a DB
default → every insert 500'd on prod while the suite was green). Run this
against a database that was brought up with `alembic upgrade head`:

    DATABASE_URL=postgresql+asyncpg://… python -m scripts.check_schema_drift

Exit 1 with the diff list when the models would generate a migration.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401 — registers every table on Base.metadata
from app.config import get_settings
from app.db import Base

# What counts as drift. The dangerous direction is a model that RELIES on a
# database default (`server_default=…`) while the migrated table has none —
# then every ORM insert fails with a NOT NULL violation, exactly the prod bug.
# The opposite (DB has a default the model doesn't declare) is harmless, as
# are JSON-vs-JSONB and index/constraint naming differences, so those stay
# out of the report to keep it actionable.
_RELEVANT = {"add_table", "remove_table", "add_column", "remove_column", "modify_nullable"}


def _flatten(diffs: list[Any]) -> list[Any]:
    out: list[Any] = []
    for d in diffs:
        if isinstance(d, list):
            out.extend(_flatten(d))
        else:
            out.append(d)
    return out


def _check(conn: Connection) -> list[str]:
    ctx = MigrationContext.configure(
        conn, opts={"compare_type": True, "compare_server_default": True}
    )
    problems: list[str] = []
    for d in _flatten(compare_metadata(ctx, Base.metadata)):
        kind = d[0]
        if kind in _RELEVANT:
            problems.append(f"{kind}: {d[1] if kind.endswith('table') else f'{d[2]}.{d[3]}'}")
        elif kind == "modify_default":
            # ("modify_default", schema, table, column, {...}, old(db), new(model))
            table, column, db_default, model_default = d[2], d[3], d[5], d[6]
            if model_default is not None and db_default is None:
                problems.append(
                    f"{table}.{column}: model expects a DB default "
                    f"({model_default.arg!s}) but the migrated column has none"
                )
    return problems


async def main() -> int:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:
            problems = await conn.run_sync(_check)
    finally:
        await engine.dispose()
    if problems:
        print("Schema drift between alembic migrations and models:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("Schema matches the models (columns, nullability, types, defaults).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
