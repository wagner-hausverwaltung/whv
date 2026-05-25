import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    impower_id: int | None = None
    name: str
    kind: str
    impower_source_type: str | None = None
    amount: Decimal | None = None
    issued_date: date | None = None
    visibility: str
    state: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    # NULL = document sits at the property root (Impower-imported and
    # pre-folder uploads land here). Otherwise references a folder in
    # the Verwalter-managed tree.
    folder_id: uuid.UUID | None = None
    uploaded_at: datetime | None = None


# ── Folder schemas ────────────────────────────────────────────────


class DocumentFolderResponse(BaseModel):
    """Single folder row. Trees are reconstructed client-side from a
    flat list — much easier to cache, sort, and re-render on mutation
    than a recursive payload, and we expect at most a few hundred
    folders per property in the worst case."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    property_id: uuid.UUID
    parent_folder_id: uuid.UUID | None = None
    name: str
    created_at: datetime
    updated_at: datetime


class DocumentFolderCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_folder_id: uuid.UUID | None = None


class DocumentFolderUpdateRequest(BaseModel):
    """Both fields are optional — pass only what you want to change. To
    move a folder back to the property root, send parent_folder_id=null
    explicitly (Pydantic v2 distinguishes from omitted via model_fields_set)."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    # Use the model's `parent_folder_id` field-set marker to detect
    # "explicit null" vs "absent". We rely on `.model_fields_set` in the
    # endpoint rather than encoding a sentinel here.
    parent_folder_id: uuid.UUID | None = None


class DocumentUpdateRequest(BaseModel):
    """Verwalter-side metadata patch for an already-uploaded document.
    Same field-set trick for explicit-null on folder_id."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    folder_id: uuid.UUID | None = None
    visibility: str | None = None
    kind: str | None = None
    issued_date: date | None = None
