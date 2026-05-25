"""document folders + documents.folder_id

Verwalter-managed folder tree for per-property documents (Item 6).
Folders are scoped to a single property — no org-wide library in v1 —
and parent_folder_id forms an arbitrarily deep tree (NULL = property
root).

Revision ID: cfa6542d23b1
Revises: 5e5a1280cad4
Create Date: 2026-05-25 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cfa6542d23b1"
down_revision: str | Sequence[str] | None = "5e5a1280cad4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "document_folders",
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
            "parent_folder_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("name", sa.String(), nullable=False),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["property_id"], ["properties.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_folder_id"], ["document_folders.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_document_folders_organization_id",
        "document_folders",
        ["organization_id"],
    )
    op.create_index(
        "ix_document_folders_property_id",
        "document_folders",
        ["property_id"],
    )
    op.create_index(
        "ix_document_folders_parent_folder_id",
        "document_folders",
        ["parent_folder_id"],
    )
    op.create_index(
        "ix_document_folders_property_parent",
        "document_folders",
        ["property_id", "parent_folder_id"],
    )

    # New column on documents linking into the folder tree. NULL means
    # the doc sits at the property root (matches the Impower-imported
    # backfill — none of those rows know about folders).
    op.add_column(
        "documents",
        sa.Column(
            "folder_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_documents_folder_id",
        "documents",
        "document_folders",
        ["folder_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_documents_folder_id", "documents", ["folder_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_documents_folder_id", table_name="documents")
    op.drop_constraint("fk_documents_folder_id", "documents", type_="foreignkey")
    op.drop_column("documents", "folder_id")

    op.drop_index(
        "ix_document_folders_property_parent", table_name="document_folders"
    )
    op.drop_index(
        "ix_document_folders_parent_folder_id", table_name="document_folders"
    )
    op.drop_index(
        "ix_document_folders_property_id", table_name="document_folders"
    )
    op.drop_index(
        "ix_document_folders_organization_id", table_name="document_folders"
    )
    op.drop_table("document_folders")
