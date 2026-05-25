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

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import AgendaItemType, AgendaItemVoteResult, AssemblyStatus


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
                raise ValueError(
                    "beschluss_text is only allowed when type=BESCHLUSS"
                )
            if self.vote_required_quorum is not None:
                raise ValueError(
                    "vote_required_quorum is only allowed when type=BESCHLUSS"
                )
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
    discussion: list[DiscussionEntryResponse] = []


# ---------- Assembly itself ----------


class CreateAssemblyRequest(BaseModel):
    property_id: uuid.UUID
    title: str = Field(..., min_length=3, max_length=300)
    description: str = Field("", max_length=50_000)
    scheduled_start: datetime
    scheduled_end: datetime
    location: str = Field(..., min_length=1, max_length=500)

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


class AssemblyResponse(BaseModel):
    """List-view summary — header + counts, no nested agenda body."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    property_id: uuid.UUID
    title: str
    status: AssemblyStatus
    scheduled_start: datetime
    scheduled_end: datetime
    actual_start: datetime | None
    actual_end: datetime | None
    location: str
    protocol_pdf_url: str | None
    protocol_uploaded_at: datetime | None
    created_at: datetime


class AssemblyDetailResponse(AssemblyResponse):
    """Detail with full agenda + discussion. Single request, no fan-out."""

    description: str
    agenda_pdf_url: str | None
    agenda_items: list[AgendaItemResponse] = []


# ---------- Protocol upload ----------


class ProtocolUploadResponse(BaseModel):
    """Echoed after a successful signed-protocol PDF upload."""

    model_config = ConfigDict(from_attributes=True)

    assembly_id: uuid.UUID
    protocol_pdf_url: str
    protocol_uploaded_at: datetime
