"""Add `heated_area_m2` and `persons` columns to `units`.

Phase A of the unit master-data gap fix. Impower's public REST API
doesn't expose the per-unit "Eigenschaften der Einheiten" panel
(MEA / Fläche / Heizfläche / Personen), so Verwalter has to enter
those values on our side. Two of the four already had columns
(`voting_share`, `area_m2`); this migration adds the missing two.

Both nullable — for MV (Mietverwaltung / RENTAL) properties MEA
is meaningless and Heizfläche is often blank in Impower too;
clients render empty cells the same way they do for `area_m2`.

Revision ID: i3e7f5a9b1c4
Revises: h2d6e4f8a9c3
"""

import sqlalchemy as sa
from alembic import op

revision = "i3e7f5a9b1c4"
down_revision = "h2d6e4f8a9c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "units",
        sa.Column("heated_area_m2", sa.Numeric(10, 2), nullable=True),
    )
    # Personen is a head-count but Impower stores 0.5-step partials
    # for shared apartments — Numeric(6,2) gives us room without
    # forcing integer rounding on import.
    op.add_column(
        "units",
        sa.Column("persons", sa.Numeric(6, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("units", "persons")
    op.drop_column("units", "heated_area_m2")
