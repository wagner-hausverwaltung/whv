"""Vollmacht: per-TOP Weisungen (Ja/Nein/Enthaltung).

Owner feedback (2026-07-28): granting a proxy should let the owner bind it
per Tagesordnungspunkt. Stored as a JSONB snapshot list of
{agenda_item_id, position, title, instruction} so the signed PDF keeps the
wording the owner actually saw, even if the agenda is edited later.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c3z8w2y6u1v7"
down_revision = "b2y7v1x5t0u6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "etv_vollmachten",
        sa.Column("voting_instructions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("etv_vollmachten", "voting_instructions")
