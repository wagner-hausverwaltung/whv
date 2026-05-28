"""Add `organization_property_selections` — org-wide saved property
selection for the admin units/fee summary box.

One row per organization (unique): the checked property ids shared by
all Verwalter of that org. The management fee is derived client-side
from these ids, so only the ids are persisted.

Revision ID: q1n5j9l3g8h4
Revises: p0m4i8k2f7g3
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "q1n5j9l3g8h4"
down_revision = "p0m4i8k2f7g3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization_property_selections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "property_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_unique_constraint(
        "uq_org_property_selection_org",
        "organization_property_selections",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_org_property_selection_org",
        "organization_property_selections",
        type_="unique",
    )
    op.drop_table("organization_property_selections")
