"""Add per-agenda-item PDF attachments to ETV.

Attendees see supporting docs inline with each Tagesordnungspunkt
(Angebotsvergleich für TOP 3, Bauplan für TOP 5, …) rather than
hunting through the protocol PDF at the end. Same storage convention
as `announcement_attachments` / `ticket_message_attachments`:
storage_url stamps `local-disk:<suffix>`; bytes live at
`{etv_attachment_dir}/{id}{suffix}`.

Revision ID: j4g8c2h5b6e1
Revises: i3e7f5a9b1c4
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "j4g8c2h5b6e1"
down_revision = "i3e7f5a9b1c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "etv_agenda_item_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agenda_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("etv_agenda_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("mime_type", sa.Text, nullable=True),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("storage_url", sa.Text, nullable=False),
        sa.Column(
            "uploaded_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_etv_agenda_item_attachments_agenda_item_id",
        "etv_agenda_item_attachments",
        ["agenda_item_id"],
    )
    op.create_index(
        "ix_etv_agenda_item_attachments_uploaded_by_user_id",
        "etv_agenda_item_attachments",
        ["uploaded_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_etv_agenda_item_attachments_uploaded_by_user_id", "etv_agenda_item_attachments")
    op.drop_index("ix_etv_agenda_item_attachments_agenda_item_id", "etv_agenda_item_attachments")
    op.drop_table("etv_agenda_item_attachments")
