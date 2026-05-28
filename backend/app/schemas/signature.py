"""Schemas for the admin Signaturen tab (ADR-0012)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SignatureRequestResponse(BaseModel):
    """One e-signature request row for the admin list."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    property_id: uuid.UUID | None = None
    recipient_email: str
    recipient_name: str | None = None
    source_filename: str
    status: str
    signed_document_id: uuid.UUID | None = None
    completed_at: datetime | None = None
    created_at: datetime
