"""ticket_category casavi taxonomy

Revision ID: 9adc2e6e9b1b
Revises: 7ee037d99e5e
Create Date: 2026-05-25 08:44:36.493214

Replaces the 4-value ticket_category enum (SCHADEN / VERWALTUNG /
HAUSGELD / SONSTIGES) with the 32-value casavi-style taxonomy. Existing
ticket rows are nuked — the staging data is throwaway, and the simpler
migration path avoids hand-mapping the four old values into the new
grouped set.

The old enum type is dropped entirely and recreated. Postgres won't let
us ALTER the enum used by a non-empty column, so we wipe the rows
first.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9adc2e6e9b1b"
down_revision: str | Sequence[str] | None = "7ee037d99e5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


NEW_VALUES: tuple[str, ...] = (
    "ALLGEMEIN_FRAGE",
    "ALLGEMEIN_KLINGEL",
    "ALLGEMEIN_DOKUMENTE",
    "ALLGEMEIN_ONBOARDING",
    "ALLGEMEIN_LOB",
    "ALLGEMEIN_RUECKRUF",
    "ALLGEMEIN_SCHLUESSEL",
    "ALLGEMEIN_TELEFONNOTIZ",
    "BUCHHALTUNG_BANK_SEPA",
    "BUCHHALTUNG_BETRIEBSKOSTEN",
    "BUCHHALTUNG_JAHRESABRECHNUNG",
    "BUCHHALTUNG_BELEGE",
    "BUCHHALTUNG_ABBUCHUNGEN",
    "VERTRIEB_BEWERTUNG",
    "VERTRIEB_BERATUNG",
    "VERTRIEB_INTERESSE",
    "MIETER_WECHSEL",
    "SCHADEN_ALLGEMEIN",
    "SCHADEN_BAUMANGEL",
    "SCHADEN_ELEMENTAR",
    "SCHADEN_FEUER",
    "SCHADEN_SCHAEDLINGE",
    "SCHADEN_STROM",
    "SCHADEN_ABWASSER",
    "SCHADEN_WASSER",
    "WEG_ANFRAGE",
    "WEG_BESCHLUSSANTRAG",
    "WEG_LEGIONELLEN",
    "SONSTIGES_DATEN",
    "SONSTIGES_BESCHLUSSUMSETZUNG",
    "SONSTIGES_ETV",
    "SONSTIGES_RELAY",
    "SONSTIGES_STOERUNG",
    "SONSTIGES_OTHER",
)
OLD_VALUES: tuple[str, ...] = ("SCHADEN", "VERWALTUNG", "HAUSGELD", "SONSTIGES")


def upgrade() -> None:
    # Nuke ticket data — staging only, per ADR/user decision.
    op.execute("DELETE FROM ticket_participants")
    op.execute("DELETE FROM ticket_messages")
    op.execute("DELETE FROM tickets")

    # Detach the column from the old enum type so we can drop it.
    op.execute("ALTER TABLE tickets ALTER COLUMN category TYPE varchar USING category::varchar")
    op.execute("DROP TYPE ticket_category")

    # Recreate with the new value set.
    new_values_sql = ", ".join(f"'{v}'" for v in NEW_VALUES)
    op.execute(f"CREATE TYPE ticket_category AS ENUM ({new_values_sql})")
    op.execute(
        "ALTER TABLE tickets ALTER COLUMN category TYPE ticket_category "
        "USING category::ticket_category"
    )


def downgrade() -> None:
    # Symmetric down — wipe + drop + recreate the old 4-value enum.
    op.execute("DELETE FROM ticket_participants")
    op.execute("DELETE FROM ticket_messages")
    op.execute("DELETE FROM tickets")

    op.execute("ALTER TABLE tickets ALTER COLUMN category TYPE varchar USING category::varchar")
    op.execute("DROP TYPE ticket_category")

    old_values_sql = ", ".join(f"'{v}'" for v in OLD_VALUES)
    op.execute(f"CREATE TYPE ticket_category AS ENUM ({old_values_sql})")
    op.execute(
        "ALTER TABLE tickets ALTER COLUMN category TYPE ticket_category "
        "USING category::ticket_category"
    )


# Silence "unused import" — sa import is the alembic-template convention.
_ = sa
