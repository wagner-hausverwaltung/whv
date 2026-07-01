"""Jahresabrechnung tracker service — read progress + tick a stage.

v1 is all-manual: every stage defaults to open and a Verwalter ticks it. The
effective list always returns all 9 stages A-I (a property with no cycle row yet
reads as "all open"), so the clients render a stable board without first having
to create anything.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    ACCOUNTING_STAGE_CODES,
    ACCOUNTING_STAGES,
    AccountingCycle,
    AccountingCycleStage,
    Property,
)
from app.schemas.accounting import (
    AccountingBoardRow,
    AccountingProgressResponse,
    AccountingStageResponse,
)


def active_accounting_year(today: date | None = None) -> int:
    """The Wirtschaftsjahr currently being settled = last calendar year. So the
    2025 cycle becomes the active one from 1 Jan 2026 — the clients default to
    this when no year is given."""
    return (today or date.today()).year - 1


async def _get_cycle(
    session: AsyncSession, property_id: uuid.UUID, year: int
) -> AccountingCycle | None:
    cycle: AccountingCycle | None = await session.scalar(
        select(AccountingCycle)
        .where(AccountingCycle.property_id == property_id, AccountingCycle.year == year)
        .options(selectinload(AccountingCycle.stages))
    )
    return cycle


async def get_progress(
    session: AsyncSession, *, property_id: uuid.UUID, year: int
) -> AccountingProgressResponse:
    cycle = await _get_cycle(session, property_id, year)
    by_code = {s.stage_code: s for s in (cycle.stages if cycle else [])}
    stages, done_count = _build_stage_list(by_code)
    return AccountingProgressResponse(
        property_id=property_id,
        year=year,
        done_count=done_count,
        total=len(ACCOUNTING_STAGES),
        stages=stages,
    )


def _build_stage_list(
    by_code: dict[str, AccountingCycleStage],
) -> tuple[list[AccountingStageResponse], int]:
    stages: list[AccountingStageResponse] = []
    done_count = 0
    for code, label in ACCOUNTING_STAGES:
        st = by_code.get(code)
        done = bool(st and st.done)
        if done:
            done_count += 1
        stages.append(
            AccountingStageResponse(
                code=code,
                label=label,
                done=done,
                done_at=st.done_at if st else None,
                note=st.note if st else None,
            )
        )
    return stages, done_count


async def get_board(
    session: AsyncSession, *, organization_id: uuid.UUID, year: int
) -> list[AccountingBoardRow]:
    """Cross-property progress board for the Verwalter — every non-deleted
    property with its stage status for the year (one row each)."""
    props = list(
        (
            await session.scalars(
                select(Property)
                .where(Property.organization_id == organization_id, Property.deleted_at.is_(None))
                .order_by(Property.name)
            )
        ).all()
    )
    if not props:
        return []
    cycles = (
        await session.scalars(
            select(AccountingCycle)
            .where(
                AccountingCycle.property_id.in_([p.id for p in props]),
                AccountingCycle.year == year,
            )
            .options(selectinload(AccountingCycle.stages))
        )
    ).all()
    by_prop: dict[uuid.UUID, dict[str, AccountingCycleStage]] = {
        c.property_id: {s.stage_code: s for s in c.stages} for c in cycles
    }
    rows: list[AccountingBoardRow] = []
    for p in props:
        stages, done_count = _build_stage_list(by_prop.get(p.id, {}))
        rows.append(
            AccountingBoardRow(
                property_id=p.id,
                property_name=p.name,
                year=year,
                done_count=done_count,
                total=len(ACCOUNTING_STAGES),
                stages=stages,
            )
        )
    return rows


async def set_stage(
    session: AsyncSession,
    *,
    property_id: uuid.UUID,
    organization_id: uuid.UUID,
    year: int,
    code: str,
    done: bool,
    note: str | None,
    user_id: uuid.UUID,
) -> AccountingProgressResponse:
    """Tick / untick one stage (Verwalter). Lazily creates the cycle + stage row
    on first edit. Commits and returns the refreshed progress."""
    if code not in ACCOUNTING_STAGE_CODES:
        raise ValueError(f"unknown stage code {code!r}")

    cycle = await _get_cycle(session, property_id, year)
    if cycle is None:
        cycle = AccountingCycle(organization_id=organization_id, property_id=property_id, year=year)
        session.add(cycle)
        await session.flush()

    st = await session.scalar(
        select(AccountingCycleStage).where(
            AccountingCycleStage.cycle_id == cycle.id,
            AccountingCycleStage.stage_code == code,
        )
    )
    if st is None:
        st = AccountingCycleStage(cycle_id=cycle.id, stage_code=code)
        session.add(st)

    st.done = done
    st.done_at = datetime.now(UTC) if done else None
    st.done_by_user_id = user_id if done else None
    if note is not None:
        st.note = note.strip() or None

    await session.commit()
    return await get_progress(session, property_id=property_id, year=year)
