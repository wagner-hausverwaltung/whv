"""etv_assemblies: protocol_extracted_* tracking columns

Revision ID: c4d9f7e1b620
Revises: b3e8c2a5f981
Create Date: 2026-05-25 18:50:00.000000

Post-meeting LLM extraction reads the signed Protokoll and merges
Beschluss outcomes (final wording, vote tallies, ANGENOMMEN/ABGELEHNT)
+ Diskussion entries into the existing agenda. Tracked separately
from invitation extraction so the admin SPA can render two distinct
"KI-extrahiert" surfaces if needed and so re-running protocol
extraction doesn't disturb the invitation provenance.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d9f7e1b620"
down_revision: Union[str, Sequence[str], None] = "b3e8c2a5f981"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "etv_assemblies",
        sa.Column("protocol_extracted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "etv_assemblies",
        sa.Column("protocol_extracted_source_document_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "etv_assemblies",
        sa.Column(
            "protocol_extracted_raw",
            sa.JSON().with_variant(
                sa.dialects.postgresql.JSONB(),  # type: ignore[attr-defined]
                "postgresql",
            ),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_etv_assemblies_protocol_extracted_source_doc",
        "etv_assemblies",
        "documents",
        ["protocol_extracted_source_document_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_etv_assemblies_protocol_extracted_source_doc",
        "etv_assemblies",
        type_="foreignkey",
    )
    op.drop_column("etv_assemblies", "protocol_extracted_raw")
    op.drop_column("etv_assemblies", "protocol_extracted_source_document_id")
    op.drop_column("etv_assemblies", "protocol_extracted_at")
