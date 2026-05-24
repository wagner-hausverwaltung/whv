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


class Ticket(OrganizationScopedMixin, TimestampMixin, Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7_pk)
    property_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
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
    author_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal_note: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        server_default="false",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        # Thread render: load messages of a ticket in chronological order.
        Index("ix_ticket_messages_thread", "ticket_id", "created_at"),
    )
