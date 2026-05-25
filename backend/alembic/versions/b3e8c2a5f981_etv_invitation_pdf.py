"""etv_assemblies: invitation_pdf_url + invitation_uploaded_at

Revision ID: b3e8c2a5f981
Revises: a1f7e6c8b234
Create Date: 2026-05-25 18:30:00.000000

Verwalter-uploaded invitation PDFs become the canonical source for
LLM extraction (replacing the failed Impower-download dependency).
Mirrors the existing protocol_pdf_url + protocol_uploaded_at pair.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3e8c2a5f981"
down_revision: Union[str, Sequence[str], None] = "a1f7e6c8b234"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "etv_assemblies",
        sa.Column("invitation_pdf_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "etv_assemblies",
        sa.Column(
            "invitation_uploaded_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("etv_assemblies", "invitation_uploaded_at")
    op.drop_column("etv_assemblies", "invitation_pdf_url")
