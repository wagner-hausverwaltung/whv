"""Add `resolution_ballots` — per-owner tokens for email voting.

Lets an eligible owner vote on an Umlaufbeschluss by email WITHOUT a
portal account: one row per (resolution, owner), a unique token behind
the public `/abstimmung/{token}` page. NULL `owner_email` = no mail on
file → the Verwalter records a postal vote manually.

Revision ID: p0m4i8k2f7g3
Revises: o9l3h7j1e6f2
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "p0m4i8k2f7g3"
down_revision = "o9l3h7j1e6f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resolution_ballots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "resolution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("circular_resolutions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_contact_id_impower", sa.BigInteger, nullable=False),
        sa.Column("owner_name", sa.Text, nullable=True),
        sa.Column("owner_email", sa.Text, nullable=True),
        sa.Column("token", sa.Text, nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_resolution_ballots_resolution_id", "resolution_ballots", ["resolution_id"]
    )
    op.create_unique_constraint(
        "uq_resolution_ballots_token", "resolution_ballots", ["token"]
    )
    op.create_unique_constraint(
        "uq_resolution_ballots_resolution_owner",
        "resolution_ballots",
        ["resolution_id", "owner_contact_id_impower"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_resolution_ballots_resolution_owner", "resolution_ballots", type_="unique"
    )
    op.drop_constraint("uq_resolution_ballots_token", "resolution_ballots", type_="unique")
    op.drop_index("ix_resolution_ballots_resolution_id", "resolution_ballots")
    op.drop_table("resolution_ballots")
