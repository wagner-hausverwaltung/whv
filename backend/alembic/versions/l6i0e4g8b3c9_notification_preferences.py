"""Add `user_notification_preferences` table.

Per-user, per-category Push/E-Mail switches. Absence of a row means
"all on" (opt-out model) — see ADR-0011. Drives recipient filtering
at every notification site (announcements, tickets, ETV comments, ETV
invitations, new documents).

Revision ID: l6i0e4g8b3c9
Revises: k5h9d3f7a2b8
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "l6i0e4g8b3c9"
down_revision = "k5h9d3f7a2b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_notification_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "category",
            sa.Enum(
                "ANNOUNCEMENT",
                "TICKET",
                "ETV_COMMENT",
                "ETV_INVITATION",
                "DOCUMENT",
                name="notification_category",
            ),
            nullable=False,
        ),
        sa.Column("push_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("email_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_user_notification_preferences_user_id",
        "user_notification_preferences",
        ["user_id"],
    )
    # One row per (user, category): the upsert in PUT
    # /me/notification-settings keys on this.
    op.create_unique_constraint(
        "uq_notification_pref_user_category",
        "user_notification_preferences",
        ["user_id", "category"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_notification_pref_user_category",
        "user_notification_preferences",
        type_="unique",
    )
    op.drop_index(
        "ix_user_notification_preferences_user_id",
        "user_notification_preferences",
    )
    op.drop_table("user_notification_preferences")
    sa.Enum(name="notification_category").drop(op.get_bind(), checkfirst=True)
