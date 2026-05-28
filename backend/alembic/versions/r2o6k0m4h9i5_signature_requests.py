"""Add `signature_requests` + the SIGNATUR document kind (ADR-0012).

Tracks DocuSeal e-signature sends (one row per "PDF → one signer"); the
`form.completed` webhook flips a row to COMPLETED and links the signed
PDF stored back in the document tree under the new SIGNATUR kind.

Revision ID: r2o6k0m4h9i5
Revises: q1n5j9l3g8h4
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "r2o6k0m4h9i5"
down_revision = "q1n5j9l3g8h4"
branch_labels = None
depends_on = None

_status = postgresql.ENUM(
    "PENDING",
    "SENT",
    "COMPLETED",
    "FAILED",
    name="signature_request_status",
)


def upgrade() -> None:
    # New value on the existing document_kind enum. PG12+ permits ADD
    # VALUE inside a transaction as long as the value isn't *used* in the
    # same transaction — we only create an unrelated table below.
    op.execute("ALTER TYPE document_kind ADD VALUE IF NOT EXISTS 'SIGNATUR'")

    _status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "signature_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "property_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("recipient_email", sa.Text, nullable=False),
        sa.Column("recipient_name", sa.Text, nullable=True),
        sa.Column("source_filename", sa.Text, nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "PENDING",
                "SENT",
                "COMPLETED",
                "FAILED",
                name="signature_request_status",
                create_type=False,
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("docuseal_template_id", sa.BigInteger, nullable=True),
        sa.Column("docuseal_submission_id", sa.BigInteger, nullable=True),
        sa.Column(
            "signed_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_user_id",
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
    op.create_index(
        "ix_signature_requests_organization_id", "signature_requests", ["organization_id"]
    )
    op.create_index(
        "ix_signature_requests_docuseal_submission_id",
        "signature_requests",
        ["docuseal_submission_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_signature_requests_docuseal_submission_id", "signature_requests")
    op.drop_index("ix_signature_requests_organization_id", "signature_requests")
    op.drop_table("signature_requests")
    op.execute("DROP TYPE signature_request_status")
    # Postgres can't easily drop a single enum value; leaving 'SIGNATUR'
    # on document_kind is harmless.
