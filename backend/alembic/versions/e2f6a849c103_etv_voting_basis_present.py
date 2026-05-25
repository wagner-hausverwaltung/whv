"""etv_agenda_items: voting_basis + present_count

Revision ID: e2f6a849c103
Revises: d8a3f29c4815
Create Date: 2026-05-25 19:25:00.000000

German WEG protocols report votes against one of three Stimmrecht
modes: per head, by MEA-share, or per Einheit. The protocol also
typically prints how many votes were present for THIS particular
vote (people walk in/out between TOPs). Both are useful evidence
trail; we extract them from the Protokoll via the LLM and surface
them on the portal alongside the Ja/Nein/Enthaltung tallies.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2f6a849c103"
down_revision: Union[str, Sequence[str], None] = "d8a3f29c4815"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    voting_basis = sa.Enum(
        "KOPF", "MEA", "OBJEKT", name="agenda_item_voting_basis"
    )
    voting_basis.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "etv_agenda_items",
        sa.Column("voting_basis", voting_basis, nullable=True),
    )
    op.add_column(
        "etv_agenda_items",
        sa.Column("present_count", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("etv_agenda_items", "present_count")
    op.drop_column("etv_agenda_items", "voting_basis")
    sa.Enum(name="agenda_item_voting_basis").drop(
        op.get_bind(), checkfirst=True
    )
