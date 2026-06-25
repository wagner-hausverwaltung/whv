"""offer_inquiries (anfragen@ auto-offer, ADR-0019)

Revision ID: c7f1a9e3b520
Revises: b2e5c8a3f470
Create Date: 2026-06-25

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c7f1a9e3b520"
down_revision = "b2e5c8a3f470"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "offer_inquiries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("sender_email", sa.Text(), nullable=False),
        sa.Column("sender_name", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("received_message_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="NEW"),
        sa.Column("art", sa.Text(), nullable=True),
        sa.Column("object_address", sa.Text(), nullable=True),
        sa.Column("units", sa.Integer(), nullable=True),
        sa.Column("desired_start", sa.Date(), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("extraction_json", sa.Text(), nullable=True),
        sa.Column("generated_offer_filename", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_message_id", sa.Text(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_offer_inquiries_organization_id", "offer_inquiries", ["organization_id"])
    op.create_index(
        "ix_offer_inquiries_received_message_id", "offer_inquiries", ["received_message_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_offer_inquiries_received_message_id", table_name="offer_inquiries")
    op.drop_index("ix_offer_inquiries_organization_id", table_name="offer_inquiries")
    op.drop_table("offer_inquiries")
