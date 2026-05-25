"""etv_assemblies.teams_meeting_url

Revision ID: d8a3f29c4815
Revises: c4d9f7e1b620
Create Date: 2026-05-25 19:05:00.000000

Hybrid ETV link. Many invitations now include a Microsoft Teams
meet-up URL; we extract it from the invitation PDF when present
and surface it as a prominent "Join Teams meeting" button on the
portal / iOS detail view. Verwalter can also paste / edit it on
the admin SPA so the LLM is a convenience, not the only source.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d8a3f29c4815"
down_revision: Union[str, Sequence[str], None] = "c4d9f7e1b620"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "etv_assemblies",
        sa.Column("teams_meeting_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("etv_assemblies", "teams_meeting_url")
