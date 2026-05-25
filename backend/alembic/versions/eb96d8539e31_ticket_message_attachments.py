"""ticket_message_attachments

Item 7: file attachments on ticket messages. Uploaded from the SPA or
extracted from inbound email MIME parts. Storage stays on local disk
(same pattern as documents); Hetzner OS migration deferred.

Revision ID: eb96d8539e31
Revises: cfa6542d23b1
Create Date: 2026-05-25 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "eb96d8539e31"
down_revision: str | Sequence[str] | None = "cfa6542d23b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "ticket_message_attachments",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "ticket_message_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_url", sa.Text(), nullable=False),
        sa.Column(
            "uploaded_by_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["ticket_message_id"], ["ticket_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ticket_message_attachments_ticket_message_id",
        "ticket_message_attachments",
        ["ticket_message_id"],
    )
    op.create_index(
        "ix_ticket_message_attachments_uploaded_by_user_id",
        "ticket_message_attachments",
        ["uploaded_by_user_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_ticket_message_attachments_uploaded_by_user_id",
        table_name="ticket_message_attachments",
    )
    op.drop_index(
        "ix_ticket_message_attachments_ticket_message_id",
        table_name="ticket_message_attachments",
    )
    op.drop_table("ticket_message_attachments")
