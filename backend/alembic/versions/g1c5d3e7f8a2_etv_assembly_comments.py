"""etv_assembly_comments

Revision ID: g1c5d3e7f8a2
Revises: f3a25b8d9e74
Create Date: 2026-05-25 20:10:00.000000

Q&A thread under an ETV detail view. Same shape as
announcement_comments minus the v1.1 features (moderation,
version history) — comments here are conversational, not formal
amendments to the protocol. The protocol stays sacred; comments
let Eigentümer ask follow-up questions and the Verwalter answer.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g1c5d3e7f8a2"
down_revision: Union[str, Sequence[str], None] = "f3a25b8d9e74"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "etv_assembly_comments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("assembly_id", sa.UUID(), nullable=False),
        sa.Column("author_user_id", sa.UUID(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "edited_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["assembly_id"], ["etv_assemblies.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_etv_assembly_comments_thread",
        "etv_assembly_comments",
        ["assembly_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_etv_assembly_comments_author_user_id"),
        "etv_assembly_comments",
        ["author_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_etv_assembly_comments_author_user_id"),
        table_name="etv_assembly_comments",
    )
    op.drop_index(
        "ix_etv_assembly_comments_thread",
        table_name="etv_assembly_comments",
    )
    op.drop_table("etv_assembly_comments")
