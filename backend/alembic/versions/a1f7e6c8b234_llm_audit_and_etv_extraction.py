"""llm_audit_log + etv_assemblies extraction columns

Revision ID: a1f7e6c8b234
Revises: e8d12fa4b903
Create Date: 2026-05-25 17:50:00.000000

Adds the two storage surfaces the LLM extraction pipeline needs
(ADR-0008):

* `llm_audit_log` — one row per LLM call, our DSGVO Art. 30 register.
  Cost dashboards + budget alarms read from this table.

* On `etv_assemblies`: four columns that track auto-extracted state
  separately from Verwalter sign-off. The Celery task fills the
  first three; a Verwalter setting `verified_at` is what flips the
  row from "draft" to "trusted" in the UI.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1f7e6c8b234"
down_revision: Union[str, Sequence[str], None] = "e8d12fa4b903"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_audit_log",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "purpose",
            sa.Text(),
            nullable=False,
            comment=(
                "Free-form feature tag — e.g. 'etv.extract_metadata'. "
                "Used to slice the cost dashboard by feature."
            ),
        ),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            comment="One of: ok, skipped_provider_unavailable, parse_error, error",
        ),
        sa.Column(
            "subject_kind",
            sa.Text(),
            nullable=True,
            comment="Domain entity touched (e.g. 'etv_assembly').",
        ),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_llm_audit_log_org_purpose_created",
        "llm_audit_log",
        ["organization_id", "purpose", "created_at"],
        unique=False,
    )

    op.add_column(
        "etv_assemblies",
        sa.Column(
            "auto_extracted_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "etv_assemblies",
        sa.Column("auto_extracted_source_document_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "etv_assemblies",
        sa.Column(
            "auto_extracted_raw",
            sa.JSON().with_variant(
                # JSONB on Postgres so we can index + query the raw
                # extraction later if needed (e.g. "which assemblies
                # had Beschluss 'Hausordnung neu fassen'?").
                sa.dialects.postgresql.JSONB(),  # type: ignore[attr-defined]
                "postgresql",
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "etv_assemblies",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "etv_assemblies",
        sa.Column("verified_by_user_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_etv_assemblies_extracted_source_doc",
        "etv_assemblies",
        "documents",
        ["auto_extracted_source_document_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_etv_assemblies_verified_by_user",
        "etv_assemblies",
        "users",
        ["verified_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_etv_assemblies_verified_by_user", "etv_assemblies", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_etv_assemblies_extracted_source_doc",
        "etv_assemblies",
        type_="foreignkey",
    )
    op.drop_column("etv_assemblies", "verified_by_user_id")
    op.drop_column("etv_assemblies", "verified_at")
    op.drop_column("etv_assemblies", "auto_extracted_raw")
    op.drop_column("etv_assemblies", "auto_extracted_source_document_id")
    op.drop_column("etv_assemblies", "auto_extracted_at")
    op.drop_index("ix_llm_audit_log_org_purpose_created", table_name="llm_audit_log")
    op.drop_table("llm_audit_log")
