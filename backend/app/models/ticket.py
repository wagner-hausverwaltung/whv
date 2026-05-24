import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._mixins import OrganizationScopedMixin, TimestampMixin, uuid7_pk


class TicketCategory(enum.StrEnum):
    SCHADEN = "SCHADEN"
    VERWALTUNG = "VERWALTUNG"
    HAUSGELD = "HAUSGELD"
    SONSTIGES = "SONSTIGES"


class TicketStatus(enum.StrEnum):
    NEU = "NEU"
    OFFEN = "OFFEN"
    WARTET_AUF_KUNDE = "WARTET_AUF_KUNDE"
    GESCHLOSSEN = "GESCHLOSSEN"


class TicketShareScope(enum.StrEnum):
    """Who else (beyond creator + Verwalter) can see + comment on this ticket.

    PRIVATE       — creator + Verwalter only (default; explicit opt-in required
                    to widen access)
    PARTICIPANTS  — also: every user in ticket_participants
    PROPERTY      — also: every user with a contract on `tickets.property_id`
                    (requires property_id set). Only the explicitly-named
                    participants get email notifications; property-scope
                    viewers see the ticket if they visit the portal but
                    don't get fan-out emails.
    """

    PRIVATE = "PRIVATE"
    PARTICIPANTS = "PARTICIPANTS"
    PROPERTY = "PROPERTY"


class TicketMessageSource(enum.StrEnum):
    """Where a ticket message originated.

    PORTAL — typed into the React portal or Jinja admin UI
    EMAIL  — arrived via the SES → SNS → /webhooks/email/inbound path
    """

    PORTAL = "PORTAL"
    EMAIL = "EMAIL"


class Ticket(OrganizationScopedMixin, TimestampMixin, Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    property_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    # When set, this ticket was created via inbound email by a sender that
    # does NOT have a WHV-Portal account. Notifications go to this address;
    # registered-user replies via the portal still work normally.
    external_sender_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    category: Mapped[TicketCategory] = mapped_column(
        Enum(TicketCategory, name="ticket_category"),
        nullable=False,
    )
    status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus, name="ticket_status"),
        nullable=False,
        default=TicketStatus.NEU,
        server_default=TicketStatus.NEU.value,
    )
    share_scope: Mapped[TicketShareScope] = mapped_column(
        Enum(TicketShareScope, name="ticket_share_scope"),
        nullable=False,
        default=TicketShareScope.PRIVATE,
        server_default=TicketShareScope.PRIVATE.value,
    )
    subject: Mapped[str] = mapped_column(Text, nullable=False)

    # Updated on every message insert so the queue sorts by activity, not by
    # the original ticket created_at.
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        # Admin queue: filter by status, sort by recency.
        Index(
            "ix_tickets_org_status_last_msg",
            "organization_id",
            "status",
            "last_message_at",
        ),
        # "My tickets" lookup for the portal.
        Index("ix_tickets_creator_status", "created_by_user_id", "status"),
    )


class TicketMessage(Base):
    """A single message in a ticket thread.

    `is_internal_note` separates Verwalter-only notes from owner-visible
    replies. Filtered out before serialization for non-Verwalter callers.
    """

    __tablename__ = "ticket_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # NULL when the message arrived via email from a non-registered sender.
    # In that case external_sender_email captures the address.
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    external_sender_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal_note: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        server_default="false",
    )
    source: Mapped[TicketMessageSource] = mapped_column(
        Enum(TicketMessageSource, name="ticket_message_source"),
        nullable=False,
        default=TicketMessageSource.PORTAL,
        server_default=TicketMessageSource.PORTAL.value,
    )
    # RFC 5322 Message-ID of the inbound email (if source=EMAIL). Used for
    # idempotency on retries + threading on outbound replies (In-Reply-To /
    # References headers).
    email_message_id: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        # Thread render: load messages of a ticket in chronological order.
        Index("ix_ticket_messages_thread", "ticket_id", "created_at"),
    )


class TicketParticipant(Base):
    """Many-to-many: users explicitly added as participants on a ticket.

    Verwalter access is implicit (no row needed). Creator access is implicit
    (`tickets.created_by_user_id`). This table only tracks the *additional*
    named viewers — they get email fan-out and can comment.
    """

    __tablename__ = "ticket_participants"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    added_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        # Lookup for "tickets I'm participating in" (future use; today only
        # consulted as a membership-check inside ticket access rules).
        Index("ix_ticket_participants_user", "user_id"),
    )
