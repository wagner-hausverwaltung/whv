"""One assistant Q&A turn, logged for the VERWALTER conversation overview
(ADR-0013).

Turns sharing a ``conversation_id`` (a per-chat-session id the client mints)
form one thread. Each row stores the question, the generated answer, the cited
sources, the retrieved doc ids, and the property the search was scoped to.
Access is VERWALTER-only (the admin endpoints). Retained indefinitely
(operator decision) — it holds users' Q&A over their own data, so it must
never be exposed outside the admin surface.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import OrganizationScopedMixin, uuid7_pk


class AssistantMessage(OrganizationScopedMixin, Base):
    __tablename__ = "assistant_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    # Per-chat-session id from the client; groups turns into one conversation.
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The property the search was scoped to (UI switcher), if any.
    property_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    abstained: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # The sources the answer actually cited:
    # [{index, document_id, page, source_kind, source_type, contact_name}].
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    # Everything retrieval pulled (superset of citations) — for auditing recall.
    retrieved_document_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_assistant_messages_org_conv", "organization_id", "conversation_id"),
        Index("ix_assistant_messages_org_created", "organization_id", "created_at"),
        Index("ix_assistant_messages_org_user", "organization_id", "actor_user_id"),
        Index("ix_assistant_messages_org_property", "organization_id", "property_id"),
    )
