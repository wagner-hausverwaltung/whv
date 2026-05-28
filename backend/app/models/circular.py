"""Umlaufbeschluss (circular resolution) tables.

WEMoG §23 Abs. 3 WEG supports two modes for written-circular owner votes:

  KLASSISCH (Textform / Allstimmigkeit) — every eligible owner must vote JA
  (no NEIN, no abstention, no missing vote) for the resolution to pass.
  Single dissent kills it.

  MEHRHEITS (Mehrheits-Umlaufbeschluss) — simple majority of cast votes,
  but only if the WEG has previously enabled this mode via an ETV
  resolution. The Verwalter sets `required_quorum` (minimum count of cast
  votes for the result to count); below that, ABGELEHNT regardless of
  YES/NO split.

Votes are stored one-per-owner (UNIQUE on (resolution_id, owner_contact_id_impower))
and can be replaced by the owner until `closes_at`. After close, the result
is auto-tallied by a Celery beat task; status flips to ANGENOMMEN or
ABGELEHNT and a result PDF is generated + emailed to all participants.
"""

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import OrganizationScopedMixin, TimestampMixin, uuid7_pk


class ResolutionMode(enum.StrEnum):
    KLASSISCH = "KLASSISCH"
    MEHRHEITS = "MEHRHEITS"


class ResolutionStatus(enum.StrEnum):
    ENTWURF = "ENTWURF"  # created but opens_at in future
    OFFEN = "OFFEN"  # voting open
    GESCHLOSSEN = "GESCHLOSSEN"  # closed, tally pending (transient — Celery beat tallies + flips)
    ANGENOMMEN = "ANGENOMMEN"  # tallied: passed
    ABGELEHNT = "ABGELEHNT"  # tallied: failed (or quorum not met)


class VoteChoice(enum.StrEnum):
    JA = "JA"
    NEIN = "NEIN"
    ENTHALTUNG = "ENTHALTUNG"


class CircularResolution(OrganizationScopedMixin, TimestampMixin, Base):
    __tablename__ = "circular_resolutions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[ResolutionMode] = mapped_column(
        Enum(ResolutionMode, name="resolution_mode"), nullable=False
    )
    status: Mapped[ResolutionStatus] = mapped_column(
        Enum(ResolutionStatus, name="resolution_status"),
        nullable=False,
        default=ResolutionStatus.ENTWURF,
        server_default=ResolutionStatus.ENTWURF.value,
    )

    opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Minimum count of cast votes for MEHRHEITS to be valid. For KLASSISCH this
    # is informational — the actual check is "every eligible owner voted JA".
    required_quorum: Mapped[int] = mapped_column(nullable=False, default=0)

    # Optional initial PDF supplied by Verwalter (e.g. the formal proposal
    # text). May point to local storage path until §1.4d iter 2 ships
    # documents-to-Hetzner-OS upload.
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Filled by the close handler. Same storage caveat as pdf_url for v1.
    result_pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Free-text outcome summary written by the tally code (e.g. "12 JA, 1 NEIN,
    # 0 Enthaltung → angenommen").
    result: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Display-only convenience: opened_on, decided_on dates extracted at create
    # so we can index efficiently if the queue ever needs to filter by date
    # range. Not strictly necessary for v1.
    opens_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    closes_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        # Queue lookup: by org + status + recency.
        Index("ix_circular_resolutions_org_status", "organization_id", "status", "closes_at"),
        # "What's open on this property right now?" — for the owner portal.
        Index("ix_circular_resolutions_property_status", "property_id", "status"),
    )


class CircularVote(Base):
    """One vote per eligible owner per resolution.

    `owner_contact_id_impower` matches the `contacts.impower_id` (the Impower
    contact ID), not the local UUID. We key on Impower ID because that's the
    stable identifier that ties an Eigentümer to their contracts; one Impower
    contact can have multiple WHV portal user accounts (rare but possible).
    The owner can change their vote (replace the row) until `closes_at`.
    """

    __tablename__ = "circular_votes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    resolution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("circular_resolutions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_contact_id_impower: Mapped[int] = mapped_column(BigInteger, nullable=False)
    choice: Mapped[VoteChoice] = mapped_column(
        Enum(VoteChoice, name="vote_choice"),
        nullable=False,
    )
    voter_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # "PORTAL_CLICK" in v1. Future values: "EMAIL_REPLY", "EPOST_PAPER",
    # "VERWALTER_PROXY" (Verwalter records an offline vote on owner's behalf).
    signature_method: Mapped[str] = mapped_column(
        Text, nullable=False, default="PORTAL_CLICK", server_default="PORTAL_CLICK"
    )

    # Free-form audit blob: ip_hash, user-agent, JWT id, anything that helps
    # a future dispute resolution. v1 captures IP-hashed + user-agent.
    evidence_jsonb: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    voted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        # One vote per owner per resolution; later updates replace the row
        # in-place via INSERT … ON CONFLICT.
        UniqueConstraint(
            "resolution_id",
            "owner_contact_id_impower",
            name="uq_circular_votes_resolution_owner",
        ),
        # Tally + audit reads scan by resolution.
        Index("ix_circular_votes_resolution", "resolution_id", "voted_at"),
    )


class ResolutionBallot(TimestampMixin, Base):
    """One per eligible owner per resolution — the unit that lets an owner
    vote by email WITHOUT a portal account.

    On "send", we materialise a ballot for every eligible owner (from
    their Impower contact). Owners WITH an email get a tokenised
    magic-link mailed (`token` → public `/abstimmung/{token}` page, no
    login); owners WITHOUT an email (`owner_email` NULL) surface as the
    "kein E-Mail"-Liste for the Verwalter, who records their postal vote
    manually. `voted_at` is stamped once a vote is cast (votes are
    one-shot — see ADR / the public endpoint).
    """

    __tablename__ = "resolution_ballots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    resolution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("circular_resolutions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_contact_id_impower: Mapped[int] = mapped_column(BigInteger, nullable=False)
    owner_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NULL → owner has no email on file: appears on the no-email list,
    # gets no mail, votes via the Verwalter's manual paper entry.
    owner_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Long random URL-safe token; the only credential the public voting
    # page needs. NULL is never used (always generated) but kept nullable
    # for forward-safety.
    token: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "resolution_id",
            "owner_contact_id_impower",
            name="uq_resolution_ballots_resolution_owner",
        ),
    )
