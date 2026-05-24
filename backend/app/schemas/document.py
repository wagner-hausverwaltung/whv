import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


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
    # File body fields stay null until Phase 1.4d iter 2 (upload to Hetzner Object Storage):
    mime_type: str | None = None
    size_bytes: int | None = None
