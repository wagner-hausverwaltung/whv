"""documents.released_at — Freigabe-Schranke für Abrechnung & Wirtschaftsplan.

Impower exportiert Abrechnungs-PDFs in dem Moment, in dem sie erzeugt werden —
auch als Entwurf (state=READY, kein Entwurfs-Marker; prod 2026-08-29: B42-
Entwürfe wurden gespiegelt und benachrichtigt). Deshalb entscheidet ab jetzt
der Verwalter, wann eine Jahresabrechnung / ein Wirtschaftsplan im Portal
erscheint und benachrichtigt.

Bestand wird freigegeben (der ist längst sichtbar und verschickt); alles, was
der Sync künftig NEU anlegt, startet zurückgehalten.
"""

import sqlalchemy as sa
from alembic import op

revision = "k0g5d9f3b4c6"
down_revision = "j9f4c8e2a3b5"
branch_labels = None
depends_on = None

_GATED = ("JAHRESABRECHNUNG", "WIRTSCHAFTSPLAN")


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE documents SET released_at = now() "
        f"WHERE kind IN {_GATED} AND deleted_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("documents", "released_at")
