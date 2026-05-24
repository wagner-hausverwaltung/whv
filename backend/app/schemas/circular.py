"""Pydantic schemas for Umlaufbeschluss endpoints."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import ResolutionMode, ResolutionStatus, VoteChoice


class CreateResolutionRequest(BaseModel):
    property_id: uuid.UUID
    title: str = Field(..., min_length=3, max_length=300)
    description: str = Field(..., min_length=3, max_length=50_000)
    mode: ResolutionMode
    opens_at: datetime
    closes_at: datetime
    # For MEHRHEITS: minimum cast-vote count for the result to count. For
    # KLASSISCH: informational. Validated server-side that closes_at > opens_at
    # and required_quorum >= 0.
    required_quorum: int = Field(0, ge=0)


class VoteRequest(BaseModel):
    choice: VoteChoice


class VoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resolution_id: uuid.UUID
    owner_contact_id_impower: int
    choice: VoteChoice
    voted_at: datetime
    signature_method: str


class ResolutionTally(BaseModel):
    """Live counts attached to a resolution detail response."""

    eligible_voters: int
    cast: int
    ja: int
    nein: int
    enthaltung: int
    # For MEHRHEITS: quorum_met = (cast >= required_quorum). For KLASSISCH:
    # always true; the real check is unanimous_yes.
    quorum_met: bool
    # KLASSISCH-only convenience: True iff every eligible owner voted JA.
    unanimous_yes: bool


class ResolutionResponse(BaseModel):
    """Summary used in list views — no votes, no description body."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    property_id: uuid.UUID
    title: str
    mode: ResolutionMode
    status: ResolutionStatus
    opens_at: datetime
    closes_at: datetime
    required_quorum: int
    decided_at: datetime | None
    created_at: datetime


class ResolutionDetailResponse(ResolutionResponse):
    """Detail view with description body, tally, votes, and the caller's own vote."""

    description: str
    pdf_url: str | None
    result_pdf_url: str | None
    result: str | None
    tally: ResolutionTally
    # Full vote log — included for Verwalter; filtered to "my vote only" for
    # owners (the handler decides which list to embed based on the caller's role).
    votes: list[VoteResponse]
    # The caller's vote if they have one (read off the votes list — kept as a
    # separate field so the React client doesn't have to scan the list).
    my_vote: VoteResponse | None = None
    # Convenience flag: is the caller an eligible voter (contract on the property)?
    am_eligible: bool = False


class CloseResolutionRequest(BaseModel):
    """Optional payload for the early-close endpoint. Empty in v1; reserved
    for future fields like 'reason' for audit."""

    reason: str | None = None


# Generic JSON evidence — the API never *receives* this, but the model stores
# it via the cast-vote handler. Captured here for documentation, not used as
# a request model.
class EvidenceJSON(BaseModel):
    ip_hash: str | None = None
    user_agent: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
