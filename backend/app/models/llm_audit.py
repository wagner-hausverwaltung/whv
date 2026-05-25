"""DSGVO Art. 30 register for LLM calls.

One row per outbound LLM call, regardless of provider. Acts as both
the legal "Verzeichnis von Verarbeitungstätigkeiten" entry and the
cost dashboard's source of truth — slicing by `purpose` gives feature-
level spend; slicing by `model` gives provider/model-level spend.

We intentionally do NOT store the prompt text or the model output:
they would either be redundant with the source document (extraction)
or contain personal data we have no business persisting twice. The
audit row records *that* a call happened, on *what subject*, with
*what budget*, and *what the outcome was* — enough to demonstrate
data-minimisation to the supervisory authority without ourselves
hoarding a parallel copy of every PDF.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import OrganizationScopedMixin, uuid7_pk


class LLMAuditLog(OrganizationScopedMixin, Base):
    __tablename__ = "llm_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid7_pk,
    )

    # Feature tag — e.g. "etv.extract_metadata", later "chat.message"
    # or "rag.query". Free-form by design; new features add new
    # values without a migration.
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)

    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # One of: "ok", "skipped_provider_unavailable", "parse_error",
    # "error". Sliced for "what's our extraction success rate?"
    # without scanning every row's error column.
    status: Mapped[str] = mapped_column(Text, nullable=False)
    # Subject identifier (e.g. the assembly UUID being extracted).
    # Lets "what did we last try on this row?" queries skip the
    # whole-table scan. Nullable because chat / RAG calls don't
    # tie to a single domain row.
    subject_kind: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
