"""Shared access-control predicates.

`active_contract_filter` is the single source of truth for "does this
contract still grant access?". A contract whose `end_date` has passed
(owner sold their unit, tenant moved out) must stop conferring portal
visibility AND stop pulling the person into notification fan-outs —
otherwise a former owner keeps seeing (and being emailed/pushed about)
a Liegenschaft they no longer belong to. Used by every query that
reaches a property/document through `contracts`.

Decision (2026-05-28): hard cutoff at `end_date`. We deliberately do
NOT also gate on `start_date` — a new owner/tenant whose contract
starts slightly in the future should still be able to onboard.
NULL `end_date` = open-ended = active.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import ColumnElement, or_

from app.models import Contract


def active_contract_filter(today: date | None = None) -> ColumnElement[bool]:
    """SQLAlchemy boolean: the contract is still active as of `today`."""
    if today is None:
        today = date.today()
    return or_(Contract.end_date.is_(None), Contract.end_date >= today)
