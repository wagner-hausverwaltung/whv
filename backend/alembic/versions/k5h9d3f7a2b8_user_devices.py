"""Add `user_devices` table for APNs push tokens.

One row per (user, APNs device token). Drives push-notification
fan-out (ETV comments / ticket messages / new tickets) to match the
existing email notifications. See ADR-0010.

Revision ID: k5h9d3f7a2b8
Revises: j4g8c2h5b6e1
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "k5h9d3f7a2b8"
down_revision = "j4g8c2h5b6e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("apns_token", sa.Text, nullable=False),
        sa.Column(
            "platform",
            sa.Enum("IOS", name="device_platform"),
            nullable=False,
            server_default="IOS",
        ),
        sa.Column(
            "environment",
            sa.Enum("SANDBOX", "PRODUCTION", name="device_environment"),
            nullable=False,
            server_default="PRODUCTION",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # SoftDeleteMixin column — dead tokens (APNs 410) get a
        # deleted_at stamp rather than a hard delete so we keep an
        # audit trail of which devices were ever registered.
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_user_devices_user_id", "user_devices", ["user_id"])
    # Unique on the token so re-registration upserts. Partial-unique
    # would be nicer (only among non-deleted) but a plain unique is
    # fine: a re-registered token reuses the same row via upsert, and
    # a soft-deleted token that comes back gets un-deleted in the
    # same upsert path.
    op.create_unique_constraint(
        "uq_user_devices_apns_token", "user_devices", ["apns_token"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_user_devices_apns_token", "user_devices", type_="unique")
    op.drop_index("ix_user_devices_user_id", "user_devices")
    op.drop_table("user_devices")
    sa.Enum(name="device_platform").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="device_environment").drop(op.get_bind(), checkfirst=True)
