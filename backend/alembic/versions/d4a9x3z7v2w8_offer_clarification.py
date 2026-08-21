"""anfragen@ clarification round-trip — offer_inquiries columns.

When extraction cannot determine the contract type (art=UNKNOWN), we no
longer stop silently: the sender gets an automatic question back, and their
reply re-runs extraction on the combined text. These two columns record that
we are waiting on an answer.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d4a9x3z7v2w8"
down_revision = "c3z8w2y6u1v7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "offer_inquiries",
        sa.Column("clarification_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "offer_inquiries",
        sa.Column("clarification_message_id", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_offer_inquiries_clarification_message_id",
        "offer_inquiries",
        ["clarification_message_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_offer_inquiries_clarification_message_id", table_name="offer_inquiries")
    op.drop_column("offer_inquiries", "clarification_message_id")
    op.drop_column("offer_inquiries", "clarification_sent_at")
