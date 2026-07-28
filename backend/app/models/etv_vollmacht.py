"""Digitale Vollmacht (proxy authorization) for an Eigentümerversammlung.

An owner delegates their vote for one assembly to a proxy (another owner,
the Beirat, the Verwalter, …). Signed in-app: the client sends a drawn
signature image, the backend composites it onto a WHV-design Vollmacht PDF
(ADR-0017) and stores it. The Verwalter sees a proxy register per meeting.

Unlike the DocuSeal `signature_requests` flow (email-only, external
signers), this is portal-user self-service — no DocuSeal, no Pro gate.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import OrganizationScopedMixin, TimestampMixin, uuid7_pk


class VollmachtStatus(enum.StrEnum):
    SIGNED = "SIGNED"  # active proxy
    REVOKED = "REVOKED"  # withdrawn by the owner before the meeting


class VollmachtVoteInstruction(enum.StrEnum):
    """Per-TOP voting instruction the owner binds their proxy to."""

    JA = "JA"
    NEIN = "NEIN"
    ENTHALTUNG = "ENTHALTUNG"


class EtvVollmacht(OrganizationScopedMixin, TimestampMixin, Base):
    __tablename__ = "etv_vollmachten"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    assembly_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("etv_assemblies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalised from the assembly so the admin register + access checks
    # can filter by property without a join.
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The owner granting the proxy. NULL if the user is later hard-deleted;
    # `principal_name` keeps the human-readable record either way.
    principal_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Snapshot of the granting owner's name as it appears on the Vollmacht.
    principal_name: Mapped[str] = mapped_column(Text, nullable=False)
    # Who is authorised to vote (free text: another owner, Beirat, Verwalter).
    proxy_name: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional restriction / Weisung ("nur TOP 3", "gegen Beschluss X").
    scope_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per-Tagesordnungspunkt Weisungen (Ja/Nein/Enthaltung). A SNAPSHOT list of
    # {agenda_item_id, position, title, instruction}: the agenda can still be
    # edited after signing, but the Vollmacht is a signed document — it must
    # keep the wording the owner actually saw. NULL/[] = Vollmacht ohne Weisung
    # (proxy votes freely).
    voting_instructions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[VollmachtStatus] = mapped_column(
        Enum(VollmachtStatus, name="vollmacht_status"),
        nullable=False,
        default=VollmachtStatus.SIGNED,
        server_default=VollmachtStatus.SIGNED.value,
    )
    signed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Generated Vollmacht PDF, `local-disk:<suffix>` convention. The drawn
    # signature is composited in at generation time, not stored separately.
    pdf_storage_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # Admin proxy register: a meeting's vollmachten.
        Index("ix_etv_vollmachten_assembly_status", "assembly_id", "status"),
    )
