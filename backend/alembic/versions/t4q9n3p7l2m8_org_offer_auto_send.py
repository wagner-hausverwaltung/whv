"""Add organizations.offer_auto_send_enabled (anfragen@ Auto-Modus, ADR-0019).

Persists the per-org "Auto-Modus" toggle exposed on Admin -> Anfragen. When
True, inbound offer inquiries that can be turned into a valid offer are emailed
automatically (no manual review). Defaults False so existing behaviour (park
for review) is unchanged until a Verwalter opts in.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "t4q9n3p7l2m8"
down_revision = "c7f1a9e3b520"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "offer_auto_send_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "offer_auto_send_enabled")
