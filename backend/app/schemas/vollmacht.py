"""Vollmacht (ETV proxy authorization) response schemas. The create flow is
multipart (proxy_name + optional scope_note + drawn signature image), so it
has no request body model — see app/api/v1/vollmachten.py."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models import VollmachtStatus, VollmachtVoteInstruction


class VollmachtVotingInstruction(BaseModel):
    """One per-TOP Weisung. `position` + `title` are snapshotted at signing
    time so a later agenda edit can't rewrite a signed document."""

    agenda_item_id: uuid.UUID
    position: int = 0
    title: str = ""
    instruction: VollmachtVoteInstruction


class VollmachtVotingInstructionsPayload(BaseModel):
    """Wrapper for the multipart `voting_instructions` JSON form field."""

    items: list[VollmachtVotingInstruction] = Field(default_factory=list, max_length=200)


class VollmachtResponse(BaseModel):
    id: uuid.UUID
    assembly_id: uuid.UUID
    property_id: uuid.UUID
    principal_user_id: uuid.UUID | None
    principal_name: str
    proxy_name: str
    scope_note: str | None
    voting_instructions: list[VollmachtVotingInstruction] = Field(default_factory=list)
    status: VollmachtStatus
    signed_at: datetime
    revoked_at: datetime | None
    has_pdf: bool = False
    # Admin proxy-register enrichment (the granting owner's login email).
    principal_email: str | None = None
