"""Clear the legacy "Automatisch aus Bestand …" description on
backfilled assemblies.

The string was internal admin guidance ("please verify date / agenda")
that leaked onto the owner portal + iOS, confusing end users. Going
forward the backfill leaves description empty (see
app/services/etv.py); this migration scrubs the rows that still
carry the placeholder text. Manually-edited descriptions remain
untouched because we only update on an exact match.

Revision ID: h2d6e4f8a9c3
Revises: g1c5d3e7f8a2
"""

from alembic import op

revision = "h2d6e4f8a9c3"
down_revision = "g1c5d3e7f8a2"
branch_labels = None
depends_on = None

# Two variants because the original code shipped with the trailing
# guidance sentence; the test fixture used a shorter version. Wipe
# both so we don't accidentally leave staging-only test rows in
# place.
_LEGACY_DESCRIPTIONS = (
    "Automatisch aus Bestand übernommen. Bitte Datum, Ort und Tagesordnung prüfen.",
    "Automatisch aus Bestand übernommen.",
)


def upgrade() -> None:
    for legacy in _LEGACY_DESCRIPTIONS:
        op.execute(
            f"UPDATE etv_assemblies SET description = '' WHERE description = '{legacy.replace(chr(39), chr(39) + chr(39))}'"
        )


def downgrade() -> None:
    # Intentionally one-way — we don't carry the legacy text back in
    # because we know it was admin noise nobody wants to see again.
    pass
