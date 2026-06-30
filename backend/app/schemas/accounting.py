"""Schemas for the Jahresabrechnung progress tracker."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AccountingStageResponse(BaseModel):
    code: str  # "A" … "I"
    label: str
    done: bool
    done_at: datetime | None = None
    note: str | None = None


class AccountingProgressResponse(BaseModel):
    property_id: uuid.UUID
    year: int
    done_count: int
    total: int
    stages: list[AccountingStageResponse]


class AccountingStageUpdate(BaseModel):
    done: bool
    # Optional note; null leaves the existing note unchanged, "" clears it.
    note: str | None = Field(default=None, max_length=2000)
