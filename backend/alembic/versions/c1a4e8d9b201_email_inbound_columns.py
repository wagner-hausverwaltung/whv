"""email_inbound_columns

Revision ID: c1a4e8d9b201
Revises: fbf593d062e7
Create Date: 2026-05-24 19:55:00.000000

Adds schema bits needed for /webhooks/email/inbound (SES → SNS → backend):

  - tickets.external_sender_email — set when ticket was created via email
    by a sender that doesn't have a WHV-Portal account; notifications go
    to this address.
  - tickets.created_by_user_id → NULLABLE — same reason (no user row for
    external sender). Pre-existing rows keep their non-null user.
  - ticket_messages.author_user_id → NULLABLE — for messages from external
    senders. Existing rows keep their non-null author.
  - ticket_messages.external_sender_email — captured per message when the
    author is external (so we can route subsequent notifications even after
    the ticket changes hands).
  - ticket_messages.source — PORTAL | EMAIL.
  - ticket_messages.email_message_id — RFC 5322 Message-ID, unique. Used
    for idempotency on SNS retries and as the In-Reply-To target on
    outbound replies that need to thread back.
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c1a4e8d9b201"
down_revision: Union[str, Sequence[str], None] = "fbf593d062e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create the new enum type first; the ADD COLUMN that uses it needs it.
    source_enum = sa.Enum("PORTAL", "EMAIL", name="ticket_message_source")
    source_enum.create(op.get_bind(), checkfirst=True)

    # --- tickets -------------------------------------------------------------
    op.add_column(
        "tickets",
        sa.Column("external_sender_email", sa.Text(), nullable=True),
    )
    op.alter_column("tickets", "created_by_user_id", nullable=True)

    # --- ticket_messages -----------------------------------------------------
    op.alter_column("ticket_messages", "author_user_id", nullable=True)
    op.add_column(
        "ticket_messages",
        sa.Column("external_sender_email", sa.Text(), nullable=True),
    )
    op.add_column(
        "ticket_messages",
        sa.Column(
            "source",
            source_enum,
            server_default="PORTAL",
            nullable=False,
        ),
    )
    op.add_column(
        "ticket_messages",
        sa.Column("email_message_id", sa.Text(), nullable=True),
    )
    # Unique constraint on email_message_id gives us idempotency for free:
    # SNS retries the same SES message with the same RFC 5322 ID and we'll
    # reject the duplicate insert.
    op.create_unique_constraint(
        "uq_ticket_messages_email_message_id",
        "ticket_messages",
        ["email_message_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "uq_ticket_messages_email_message_id", "ticket_messages", type_="unique"
    )
    op.drop_column("ticket_messages", "email_message_id")
    op.drop_column("ticket_messages", "source")
    op.drop_column("ticket_messages", "external_sender_email")
    # NOTE: re-tightening NOT NULL on author_user_id / created_by_user_id is
    # NOT performed on downgrade — by the time downgrade runs, the table
    # might already contain rows with NULLs that would fail validation. The
    # nullable widening is effectively one-way; if you really need to undo
    # it, do a manual cleanup pass first.
    op.drop_column("tickets", "external_sender_email")
    sa.Enum(name="ticket_message_source").drop(op.get_bind(), checkfirst=True)
