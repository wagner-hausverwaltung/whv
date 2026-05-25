"""announcement_send_attempts table

Per-recipient log of every fan-out attempt. The Celery publish task
writes a SUCCESS or FAILED row per recipient. Admin SPA reads the
list on the detail page, and a "Erneut senden" button finds the
failed rows + replays them. The table is append-only — retries write
new rows, the original FAILED row stays in the audit trail.

Revision ID: e3f8b2cd5a91
Revises: d7a91c4f3e28
Create Date: 2026-05-25 16:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3f8b2cd5a91"
down_revision: str | Sequence[str] | None = "d7a91c4f3e28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Emit CREATE TYPE explicitly first so the column reference below
    # finds it. Using postgresql.ENUM with create_type=False on the
    # column reuse keeps SA from re-emitting CREATE TYPE inside the
    # CREATE TABLE statement — sa.Enum's create_type flag turns out
    # not to suppress the implicit creation path on op.create_table()
    # in SA 2.0; the PG-specific subtype's flag does.
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE send_attempt_status AS ENUM ('SUCCESS', 'FAILED'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )
    status_enum = postgresql.ENUM(
        "SUCCESS",
        "FAILED",
        name="send_attempt_status",
        create_type=False,
    )

    op.create_table(
        "announcement_send_attempts",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "announcement_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        # Captured at send time. Even if the user is later deleted we
        # still have the address that the email actually went to —
        # critical for "who exactly didn't get my Mitteilung".
        sa.Column("recipient_email", sa.Text(), nullable=False),
        # NULL when the user was resolved via a stale prior-attempt
        # replay and has since been hard-deleted. Most rows fill this.
        sa.Column(
            "recipient_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("status", status_enum, nullable=False),
        # Empty / NULL on SUCCESS, populated with `str(EmailError)[:500]`
        # on FAILED.
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["announcement_id"],
            ["announcements.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_announcement_send_attempts_announcement_id",
        "announcement_send_attempts",
        ["announcement_id"],
    )
    op.create_index(
        "ix_announcement_send_attempts_status",
        "announcement_send_attempts",
        ["announcement_id", "status"],
    )
    op.create_index(
        "ix_announcement_send_attempts_recipient_user_id",
        "announcement_send_attempts",
        ["recipient_user_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_announcement_send_attempts_recipient_user_id",
        table_name="announcement_send_attempts",
    )
    op.drop_index(
        "ix_announcement_send_attempts_status",
        table_name="announcement_send_attempts",
    )
    op.drop_index(
        "ix_announcement_send_attempts_announcement_id",
        table_name="announcement_send_attempts",
    )
    op.drop_table("announcement_send_attempts")
    sa.Enum(name="send_attempt_status").drop(op.get_bind(), checkfirst=True)
