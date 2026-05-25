"""etv_assemblies: protocol_verified_at + protocol_verified_by_user_id

Revision ID: f3a25b8d9e74
Revises: e2f6a849c103
Create Date: 2026-05-25 19:55:00.000000

Splits the single verification gate into two — one per extraction
stage. The existing `verified_at` keeps its column name and now
semantically means "Verwalter signed off on the invitation
extraction"; the protocol extraction has its own gate and its own
"Daten bestätigen" button.

The previous design with one shared `verified_at` blocked the
protocol extractor from running after the Verwalter had verified
the invitation, which is the natural workflow (verify invitation
when uploaded → meeting happens → upload protocol → expect
extraction to fire). Audit log showed two "skipped: already
verified" rows on a real upload — the bug surfaced live.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3a25b8d9e74"
down_revision: Union[str, Sequence[str], None] = "e2f6a849c103"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "etv_assemblies",
        sa.Column("protocol_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "etv_assemblies",
        sa.Column("protocol_verified_by_user_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_etv_assemblies_protocol_verified_by_user",
        "etv_assemblies",
        "users",
        ["protocol_verified_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_etv_assemblies_protocol_verified_by_user",
        "etv_assemblies",
        type_="foreignkey",
    )
    op.drop_column("etv_assemblies", "protocol_verified_by_user_id")
    op.drop_column("etv_assemblies", "protocol_verified_at")
