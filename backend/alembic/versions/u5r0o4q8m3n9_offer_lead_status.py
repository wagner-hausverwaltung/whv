"""Add offer_inquiries.lead_status (manual sales status, ADR-0019).

A Verwalter-set per-offer status (OPEN / ON_HOLD / ACCEPTED / DECLINED),
independent of the processing `status`. New inquiries default to OPEN.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "u5r0o4q8m3n9"
down_revision = "t4q9n3p7l2m8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "offer_inquiries",
        sa.Column(
            "lead_status",
            sa.Text(),
            nullable=False,
            server_default="OPEN",
        ),
    )


def downgrade() -> None:
    op.drop_column("offer_inquiries", "lead_status")
