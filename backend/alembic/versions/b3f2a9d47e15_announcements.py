"""announcements + attachments + comments

Property-scoped Mitteilungen: admin authors title + body + attachments,
notifications fan out 10 min after creation (each edit resets the timer),
end users can comment and admins can hide comments.

Three tables:
  - announcements                — title/body/audience flags/timer columns
  - announcement_attachments     — N files per announcement (same storage
                                   convention as ticket_message_attachments)
  - announcement_comments        — user-authored thread under each
                                   published announcement; hide-only
                                   moderation (is_hidden + audit fields).

Revision ID: b3f2a9d47e15
Revises: eb96d8539e31
Create Date: 2026-05-25 14:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3f2a9d47e15"
down_revision: str | Sequence[str] | None = "eb96d8539e31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "announcements",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "organization_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "property_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "body", sa.Text(), server_default=sa.text("''"), nullable=False
        ),
        # Three role flags; CHECK ensures at least one is true so an
        # announcement can never be created with no audience.
        sa.Column(
            "audience_eigentuemer",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "audience_mieter",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "audience_beirat",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
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
        # Timer column. Initially created_at + 10 min; bumped to now()+10
        # on each edit while still unpublished. The publish Celery beat
        # finds rows where this <= now() AND notification_sent_at IS NULL.
        sa.Column(
            "scheduled_publish_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        # NULL until the fan-out task succeeds. Doubles as the "is
        # published" flag — non-admin queries filter out NULL rows.
        sa.Column(
            "notification_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["property_id"], ["properties.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "audience_eigentuemer OR audience_mieter OR audience_beirat",
            name="ck_announcements_audience_at_least_one",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_announcements_organization_id",
        "announcements",
        ["organization_id"],
    )
    op.create_index(
        "ix_announcements_property_id",
        "announcements",
        ["property_id"],
    )
    op.create_index(
        "ix_announcements_created_by_user_id",
        "announcements",
        ["created_by_user_id"],
    )
    # List query: "all announcements for property, newest first".
    op.create_index(
        "ix_announcements_property_scheduled",
        "announcements",
        ["property_id", sa.text("scheduled_publish_at DESC")],
    )
    # Celery scan: find rows due for publish. Partial index keeps it tiny
    # — once notification_sent_at is set or the row is soft-deleted, it
    # drops out of the index, so the scheduler scan is always cheap.
    op.create_index(
        "ix_announcements_due_for_publish",
        "announcements",
        ["scheduled_publish_at"],
        postgresql_where=sa.text(
            "notification_sent_at IS NULL AND deleted_at IS NULL"
        ),
    )

    op.create_table(
        "announcement_attachments",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "announcement_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        # Same "local-disk:<suffix>" convention as ticket_message_attachments
        # (see app/models/ticket.py); the storage helper resolves to
        # {announcement_attachment_dir}/{id}{suffix}.
        sa.Column("storage_url", sa.Text(), nullable=False),
        sa.Column(
            "uploaded_by_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["announcement_id"], ["announcements.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_announcement_attachments_announcement_id",
        "announcement_attachments",
        ["announcement_id"],
    )
    op.create_index(
        "ix_announcement_attachments_uploaded_by_user_id",
        "announcement_attachments",
        ["uploaded_by_user_id"],
    )

    op.create_table(
        "announcement_comments",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "announcement_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "author_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
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
        # Hide-only moderation: row stays in the DB, admins can unhide.
        # Non-admin reads filter is_hidden = false.
        sa.Column(
            "is_hidden",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "hidden_by_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("hidden_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["announcement_id"], ["announcements.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["hidden_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_announcement_comments_announcement_id",
        "announcement_comments",
        ["announcement_id"],
    )
    op.create_index(
        "ix_announcement_comments_author_user_id",
        "announcement_comments",
        ["author_user_id"],
    )
    # Thread render: load comments of an announcement chronologically.
    op.create_index(
        "ix_announcement_comments_thread",
        "announcement_comments",
        ["announcement_id", "created_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_announcement_comments_thread", table_name="announcement_comments"
    )
    op.drop_index(
        "ix_announcement_comments_author_user_id",
        table_name="announcement_comments",
    )
    op.drop_index(
        "ix_announcement_comments_announcement_id",
        table_name="announcement_comments",
    )
    op.drop_table("announcement_comments")

    op.drop_index(
        "ix_announcement_attachments_uploaded_by_user_id",
        table_name="announcement_attachments",
    )
    op.drop_index(
        "ix_announcement_attachments_announcement_id",
        table_name="announcement_attachments",
    )
    op.drop_table("announcement_attachments")

    op.drop_index(
        "ix_announcements_due_for_publish", table_name="announcements"
    )
    op.drop_index(
        "ix_announcements_property_scheduled", table_name="announcements"
    )
    op.drop_index(
        "ix_announcements_created_by_user_id", table_name="announcements"
    )
    op.drop_index("ix_announcements_property_id", table_name="announcements")
    op.drop_index(
        "ix_announcements_organization_id", table_name="announcements"
    )
    op.drop_table("announcements")
