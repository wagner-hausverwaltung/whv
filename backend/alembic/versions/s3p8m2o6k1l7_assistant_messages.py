"""Add `assistant_messages` — the logged RAG assistant Q&A turns (ADR-0013).

One row per question/answer; turns sharing `conversation_id` form a thread.
Powers the VERWALTER-only conversation overview (question, answer, cited
sources, property scope, user). Retained indefinitely.

Revision ID: s3p8m2o6k1l7
Revises: r2o6k0m4h9i5
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "s3p8m2o6k1l7"
down_revision = "r2o6k0m4h9i5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("abstained", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("citations", postgresql.JSONB, nullable=True),
        sa.Column("retrieved_document_ids", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_assistant_messages_org_conv",
        "assistant_messages",
        ["organization_id", "conversation_id"],
    )
    op.create_index(
        "ix_assistant_messages_org_created", "assistant_messages", ["organization_id", "created_at"]
    )
    op.create_index(
        "ix_assistant_messages_org_user", "assistant_messages", ["organization_id", "actor_user_id"]
    )
    op.create_index(
        "ix_assistant_messages_org_property",
        "assistant_messages",
        ["organization_id", "property_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_messages_org_property", "assistant_messages")
    op.drop_index("ix_assistant_messages_org_user", "assistant_messages")
    op.drop_index("ix_assistant_messages_org_created", "assistant_messages")
    op.drop_index("ix_assistant_messages_org_conv", "assistant_messages")
    op.drop_table("assistant_messages")
