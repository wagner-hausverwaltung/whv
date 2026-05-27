"""Pydantic schemas for Eigentümerversammlung endpoints.

The model is strictly nested:

    AssemblyDetailResponse
      ├── agenda_items: list[AgendaItemResponse]
      │                   └── discussion: list[DiscussionEntryResponse]
      └── (assembly header fields)

List views (`AssemblyResponse`) omit agenda + discussion to keep the
payload tight. Detail views fetch the full tree in a single request.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import (
    AgendaItemType,
    AgendaItemVoteResult,
    AgendaItemVotingBasis,
    AssemblyStatus,
)

# ---------- Agenda items ----------


class CreateAgendaItemRequest(BaseModel):
    position: int = Field(..., ge=1, le=999)
    type: AgendaItemType
    title: str = Field(..., min_length=1, max_length=300)
    body: str = Field("", max_length=20_000)
    beschluss_text: str | None = Field(None, max_length=20_000)
    vote_required_quorum: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def beschluss_text_only_for_beschluss(self) -> "CreateAgendaItemRequest":
        # INFORMATION / DISKUSSION TOPs don't have a resolution wording —
        # rejecting them at the schema keeps the data model honest.
        if self.type != AgendaItemType.BESCHLUSS:
            if self.beschluss_text is not None:
                raise ValueError("beschluss_text is only allowed when type=BESCHLUSS")
            if self.vote_required_quorum is not None:
                raise ValueError("vote_required_quorum is only allowed when type=BESCHLUSS")
        return self


class UpdateAgendaItemRequest(BaseModel):
    """Partial update — admin can edit any field. Position changes
    trigger a re-pack on the assembly's list of TOPs."""

    position: int | None = Field(None, ge=1, le=999)
    type: AgendaItemType | None = None
    title: str | None = Field(None, min_length=1, max_length=300)
    body: str | None = Field(None, max_length=20_000)
    beschluss_text: str | None = Field(None, max_length=20_000)
    vote_yes: int | None = Field(None, ge=0)
    vote_no: int | None = Field(None, ge=0)
    vote_abstain: int | None = Field(None, ge=0)
    vote_required_quorum: int | None = Field(None, ge=0)
    vote_result: AgendaItemVoteResult | None = None
    voting_basis: AgendaItemVotingBasis | None = None
    present_count: int | None = Field(None, ge=0)


class DiscussionEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agenda_item_id: uuid.UUID
    position: int
    speaker_label: str
    content: str
    created_at: datetime


class CreateDiscussionEntryRequest(BaseModel):
    position: int = Field(..., ge=1, le=999)
    speaker_label: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1, max_length=20_000)


class AgendaItemAttachmentResponse(BaseModel):
    """One supporting file attached to a Tagesordnungspunkt — PDF,
    photo, spreadsheet. Returned in the assembly-detail tree under
    each agenda item so the SPA + iOS render inline preview/download
    buttons without an extra round-trip."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    mime_type: str | None = None
    size_bytes: int


class AgendaItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    assembly_id: uuid.UUID
    position: int
    type: AgendaItemType
    title: str
    body: str
    beschluss_text: str | None
    vote_yes: int
    vote_no: int
    vote_abstain: int
    vote_required_quorum: int | None
    vote_result: AgendaItemVoteResult | None
    voting_basis: AgendaItemVotingBasis | None = None
    present_count: int | None = None
    discussion: list[DiscussionEntryResponse] = []
    # Files attached to this specific TOP. Empty when the
    # Verwalter hasn't uploaded anything yet (the common case).
    attachments: list[AgendaItemAttachmentResponse] = []


# ---------- Assembly itself ----------


class CreateAssemblyRequest(BaseModel):
    property_id: uuid.UUID
    title: str = Field(..., min_length=3, max_length=300)
    description: str = Field("", max_length=50_000)
    scheduled_start: datetime
    scheduled_end: datetime
    location: str = Field(..., min_length=1, max_length=500)
    teams_meeting_url: str | None = Field(default=None, max_length=2000)

    @field_validator("teams_meeting_url", mode="before")
    @classmethod
    def _empty_string_is_null(cls, v: object) -> object:
        # Form clients (the admin SPA) PATCH "" to clear the field;
        # null-on-empty avoids storing a meaningless empty string and
        # keeps the "is link set?" check in views simple.
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @model_validator(mode="after")
    def end_after_start(self) -> "CreateAssemblyRequest":
        if self.scheduled_end <= self.scheduled_start:
            raise ValueError("scheduled_end must be after scheduled_start")
        return self


class UpdateAssemblyRequest(BaseModel):
    """Partial update for an assembly header."""

    title: str | None = Field(None, min_length=3, max_length=300)
    description: str | None = Field(None, max_length=50_000)
    status: AssemblyStatus | None = None
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    location: str | None = Field(None, min_length=1, max_length=500)
    agenda_pdf_url: str | None = None
    # Empty string is the sentinel for "clear it" so a Verwalter can
    # remove a stale link via the same PATCH that updates other
    # header fields. Real URLs run a couple hundred characters
    # (Teams meetup-join URLs encode tenant + conversation IDs).
    teams_meeting_url: str | None = Field(None, max_length=2000)

    @field_validator("teams_meeting_url", mode="before")
    @classmethod
    def _empty_string_is_null(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            return None
        return v


class AssemblyResponse(BaseModel):
    """List-view summary — header + counts, no nested agenda body.

    `property_name` + `property_hr_id` are denormalised onto the
    response so every cross-property surface (admin queue, owner
    list across multiple properties, future iOS list) can render the
    Liegenschaft without a per-row fetch. Builders that don't have
    the property to hand (rare; mostly tests + unscoped usage) leave
    them null.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    property_id: uuid.UUID
    property_name: str | None = None
    property_hr_id: str | None = None
    title: str
    status: AssemblyStatus
    scheduled_start: datetime
    scheduled_end: datetime
    actual_start: datetime | None
    actual_end: datetime | None
    location: str
    teams_meeting_url: str | None = None
    invitation_pdf_url: str | None = None
    invitation_uploaded_at: datetime | None = None
    protocol_pdf_url: str | None
    protocol_uploaded_at: datetime | None
    # LLM extraction tracking (ADR-0008). Two surfaces:
    #   auto_extracted_at      — Einladung was parsed (pre-meeting)
    #   protocol_extracted_at  — Protokoll was parsed (post-meeting)
    # The admin SPA shows a "KI-extrahiert · bitte prüfen" badge while
    # EITHER stamp is set AND verified_at is null.
    auto_extracted_at: datetime | None = None
    protocol_extracted_at: datetime | None = None
    # Two-stage verification: invitation-side (`verified_at`) and
    # protocol-side (`protocol_verified_at`). Independent. Either or
    # both can be set.
    verified_at: datetime | None = None
    protocol_verified_at: datetime | None = None
    created_at: datetime


class AssemblyDetailResponse(AssemblyResponse):
    """Detail with full agenda + discussion. Single request, no fan-out."""

    description: str
    agenda_pdf_url: str | None
    agenda_items: list[AgendaItemResponse] = []


# ---------- Invitation upload ----------


# ---------- Assembly comments (Q&A thread) ----------


class AssemblyCommentResponse(BaseModel):
    """One Q&A entry. `author_role` is denormalised on the response
    so the portal can badge "Verwalter" replies visually without a
    separate fetch."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    assembly_id: uuid.UUID
    author_user_id: uuid.UUID
    author_label: str  # email or display name
    author_role: str  # "verwalter" | "eigentuemer" | "mieter" | "beirat" | "dienstleister"
    body: str
    created_at: datetime
    edited_at: datetime | None


class CreateAssemblyCommentRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=10_000)


class UpdateAssemblyCommentRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=10_000)


class InvitationUploadResponse(BaseModel):
    """Echoed after a successful Einladung PDF upload. The extraction
    task is enqueued before the response returns; the admin SPA polls
    `/admin/assemblies/{id}` to see when `auto_extracted_at` flips."""

    model_config = ConfigDict(from_attributes=True)

    assembly_id: uuid.UUID
    invitation_pdf_url: str
    invitation_uploaded_at: datetime
    extraction_enqueued: bool


# ---------- Protocol upload ----------


class ProtocolUploadResponse(BaseModel):
    """Echoed after a successful signed-protocol PDF upload. The
    extraction task is enqueued before the response returns; the
    admin SPA polls `/admin/assemblies/{id}` to see when
    `protocol_extracted_at` flips."""

    model_config = ConfigDict(from_attributes=True)

    assembly_id: uuid.UUID
    protocol_pdf_url: str
    protocol_uploaded_at: datetime
    extraction_enqueued: bool = False
