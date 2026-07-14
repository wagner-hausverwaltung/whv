"""Documents: make the visibility column real.

The portal filter never evaluated `visibility`; every row sat at the
PRIVATE server-default while behaving like ALL. Now that the filter
enforces it: flip everything to ALL (preserves exactly today's behavior),
EXCEPT SEPA-Mandat/Lastschrift documents → PRIVATE (the leak that
triggered this: owners saw each other's mandates). New default is ALL.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b2y7v1x5t0u6"
down_revision = "a1x6u0w4s9t5"
branch_labels = None
depends_on = None

_SEPA_PATTERN = "sepa|mandat|lastschrift"


def upgrade() -> None:
    op.execute("UPDATE documents SET visibility = 'ALL' WHERE visibility = 'PRIVATE'")
    op.execute(
        f"UPDATE documents SET visibility = 'PRIVATE' WHERE name ~* '{_SEPA_PATTERN}'"
    )
    op.alter_column(
        "documents",
        "visibility",
        server_default=sa.text("'ALL'"),
        existing_type=sa.Enum(name="document_visibility"),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Restore the old default; collapse everything back to PRIVATE (the
    # pre-migration uniform state — per-row history isn't recoverable).
    op.alter_column(
        "documents",
        "visibility",
        server_default=sa.text("'PRIVATE'"),
        existing_type=sa.Enum(name="document_visibility"),
        existing_nullable=False,
    )
    op.execute("UPDATE documents SET visibility = 'PRIVATE'")
