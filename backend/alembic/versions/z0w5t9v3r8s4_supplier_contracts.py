"""Versorgungsverträge — supplier_contracts table.

Per-property supply/service contracts (Versicherung, Strom, Gas, Müll, …)
with term + pricing metadata and optional links to the billing meter and the
Dienstleister contact. Verwalter-only surface.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "z0w5t9v3r8s4"
down_revision = "y9v4s8u2q7r3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "supplier_contracts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "property_id",
            UUID(as_uuid=True),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column(
            "contact_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("contract_number", sa.Text(), nullable=True),
        sa.Column("customer_number", sa.Text(), nullable=True),
        sa.Column(
            "meter_id",
            UUID(as_uuid=True),
            sa.ForeignKey("meters.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("cancellation_months", sa.Integer(), nullable=True),
        sa.Column("auto_renew", sa.Boolean(), nullable=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=True),
        sa.Column("price_period", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_supplier_contracts_organization_id", "supplier_contracts", ["organization_id"]
    )
    op.create_index("ix_supplier_contracts_property_id", "supplier_contracts", ["property_id"])
    op.create_index(
        "ix_supplier_contracts_org_category",
        "supplier_contracts",
        ["organization_id", "category"],
    )


def downgrade() -> None:
    op.drop_index("ix_supplier_contracts_org_category", table_name="supplier_contracts")
    op.drop_index("ix_supplier_contracts_property_id", table_name="supplier_contracts")
    op.drop_index("ix_supplier_contracts_organization_id", table_name="supplier_contracts")
    op.drop_table("supplier_contracts")
