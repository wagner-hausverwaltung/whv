"""Add offer_inquiries reminder tracking + persisted as-sent request (ADR-0019).

- ``sent_request_json``: the exact OfferGenerateRequest JSON used when the offer
  was emailed, so the Verwalter can re-download the as-sent offer byte-for-byte
  (the PDF itself is regenerated on demand, not stored).
- ``last_reminder_at`` / ``reminder_count``: friendly follow-up reminder tracking
  so the UI can show "Erinnerung gesendet am …" and avoid double-sends.

All three are additive + backward-compatible: existing rows get NULL / 0.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "x8u3r7t1p6q2"
down_revision = "w7t2q6s0o5p1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "offer_inquiries",
        sa.Column("sent_request_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "offer_inquiries",
        sa.Column("last_reminder_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "offer_inquiries",
        sa.Column(
            "reminder_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("offer_inquiries", "reminder_count")
    op.drop_column("offer_inquiries", "last_reminder_at")
    op.drop_column("offer_inquiries", "sent_request_json")
