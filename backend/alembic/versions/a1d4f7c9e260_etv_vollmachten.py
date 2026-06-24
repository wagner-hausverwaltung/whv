"""Add `etv_vollmachten` — digital proxy authorizations for an ETV (ADR-0017).

An owner delegates their vote for one assembly to a proxy; signed in-app
(drawn signature composited onto a WHV-design PDF). Verwalter sees a proxy
register per meeting.

Revision ID: a1d4f7c9e260
Revises: f8b3c1a9d240
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a1d4f7c9e260"
down_revision = "f8b3c1a9d240"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "etv_vollmachten",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "assembly_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("etv_assemblies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "property_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "principal_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("principal_name", sa.Text, nullable=False),
        sa.Column("proxy_name", sa.Text, nullable=False),
        sa.Column("scope_note", sa.Text, nullable=True),
        sa.Column(
            "status",
            sa.Enum("SIGNED", "REVOKED", name="vollmacht_status"),
            nullable=False,
            server_default="SIGNED",
        ),
        sa.Column(
            "signed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pdf_storage_url", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_etv_vollmachten_organization_id", "etv_vollmachten", ["organization_id"])
    op.create_index("ix_etv_vollmachten_assembly_id", "etv_vollmachten", ["assembly_id"])
    op.create_index(
        "ix_etv_vollmachten_principal_user_id", "etv_vollmachten", ["principal_user_id"]
    )
    op.create_index(
        "ix_etv_vollmachten_assembly_status", "etv_vollmachten", ["assembly_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_etv_vollmachten_assembly_status", "etv_vollmachten")
    op.drop_index("ix_etv_vollmachten_principal_user_id", "etv_vollmachten")
    op.drop_index("ix_etv_vollmachten_assembly_id", "etv_vollmachten")
    op.drop_index("ix_etv_vollmachten_organization_id", "etv_vollmachten")
    op.drop_table("etv_vollmachten")
    sa.Enum(name="vollmacht_status").drop(op.get_bind(), checkfirst=True)
