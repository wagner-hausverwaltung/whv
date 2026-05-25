"""etv_assemblies + etv_agenda_items + etv_discussion_entries

Adds the schema for **Eigentümerversammlung** (in-person owner assembly,
the WEG counterpart to a circular Umlaufbeschluss). The three new tables
are structured around the document the Verwalter actually produces:

    Assembly  (metadata: title, location, start/end, status, protocol)
       └── AgendaItem  (one row per TOP — Tagesordnungspunkt)
              └── DiscussionEntry  (per-TOP discussion: who said what)

Beschluss tallies live on the agenda item itself (yes/no/abstain counts +
optional required_quorum + final result) — there is no separate
`etv_votes` row-per-owner table, because for an in-person ETV the vote
record IS the signed protocol PDF, not the click stream. (Contrast with
circular_resolutions where individual click-votes are the authoritative
record.)

Revision ID: e8d12fa4b903
Revises: d9f31a8b5e72
Create Date: 2026-05-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8d12fa4b903'
down_revision: Union[str, Sequence[str], None] = 'd9f31a8b5e72'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'etv_assemblies',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('property_id', sa.UUID(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), server_default='', nullable=False),
        sa.Column(
            'status',
            sa.Enum(
                'GEPLANT', 'EINGELADEN', 'ABGEHALTEN', 'ABGESAGT',
                name='assembly_status',
            ),
            server_default='GEPLANT',
            nullable=False,
        ),
        sa.Column('scheduled_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('scheduled_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('actual_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('actual_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('location', sa.Text(), nullable=False),
        sa.Column('agenda_pdf_url', sa.Text(), nullable=True),
        sa.Column('protocol_pdf_url', sa.Text(), nullable=True),
        sa.Column('protocol_uploaded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['property_id'], ['properties.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_etv_assemblies_property_id'),
        'etv_assemblies', ['property_id'], unique=False,
    )
    op.create_index(
        op.f('ix_etv_assemblies_organization_id'),
        'etv_assemblies', ['organization_id'], unique=False,
    )
    op.create_index(
        op.f('ix_etv_assemblies_created_by'),
        'etv_assemblies', ['created_by'], unique=False,
    )
    # Property-scoped queue: "show me the next ETV for this property" +
    # "show me past ETVs sorted newest first." Single composite serves both.
    op.create_index(
        'ix_etv_assemblies_property_status_start',
        'etv_assemblies', ['property_id', 'status', 'scheduled_start'],
        unique=False,
    )
    # Admin cross-property queue: "all upcoming ETVs across all
    # properties in the org."
    op.create_index(
        'ix_etv_assemblies_org_status_start',
        'etv_assemblies', ['organization_id', 'status', 'scheduled_start'],
        unique=False,
    )

    op.create_table(
        'etv_agenda_items',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('assembly_id', sa.UUID(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column(
            'type',
            sa.Enum(
                'INFORMATION', 'BESCHLUSS', 'DISKUSSION',
                name='agenda_item_type',
            ),
            nullable=False,
        ),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('body', sa.Text(), server_default='', nullable=False),
        # The wording of the resolution. Only meaningful for type=BESCHLUSS;
        # NULL for INFORMATION/DISKUSSION. We store separately from `body`
        # so the protocol PDF generator can render it verbatim.
        sa.Column('beschluss_text', sa.Text(), nullable=True),
        sa.Column('vote_yes', sa.Integer(), server_default='0', nullable=False),
        sa.Column('vote_no', sa.Integer(), server_default='0', nullable=False),
        sa.Column('vote_abstain', sa.Integer(), server_default='0', nullable=False),
        # NULL = no quorum required; else the integer threshold for
        # cast votes below which the result is automatically ABGELEHNT.
        sa.Column('vote_required_quorum', sa.Integer(), nullable=True),
        sa.Column(
            'vote_result',
            sa.Enum(
                'ANGENOMMEN', 'ABGELEHNT',
                name='agenda_item_vote_result',
            ),
            nullable=True,
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['assembly_id'], ['etv_assemblies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('assembly_id', 'position', name='uq_etv_agenda_items_assembly_position'),
        # Cheap sanity rail: a BESCHLUSS row should carry beschluss_text,
        # the others may not. Enforce via app layer (Pydantic) — DB-level
        # CHECK gets unwieldy when types diverge later.
    )
    op.create_index(
        op.f('ix_etv_agenda_items_assembly_id'),
        'etv_agenda_items', ['assembly_id'], unique=False,
    )

    op.create_table(
        'etv_discussion_entries',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('agenda_item_id', sa.UUID(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        # Free-text speaker label — attendees often don't have portal
        # accounts (Vermieter showing up, proxies, etc.), so we keep
        # this as a string rather than a FK to users/contacts.
        sa.Column('speaker_label', sa.Text(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['agenda_item_id'], ['etv_agenda_items.id'], ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'agenda_item_id', 'position',
            name='uq_etv_discussion_entries_agenda_item_position',
        ),
    )
    op.create_index(
        op.f('ix_etv_discussion_entries_agenda_item_id'),
        'etv_discussion_entries', ['agenda_item_id'], unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f('ix_etv_discussion_entries_agenda_item_id'),
        table_name='etv_discussion_entries',
    )
    op.drop_table('etv_discussion_entries')
    op.drop_index(
        op.f('ix_etv_agenda_items_assembly_id'),
        table_name='etv_agenda_items',
    )
    op.drop_table('etv_agenda_items')
    op.drop_index(
        'ix_etv_assemblies_org_status_start',
        table_name='etv_assemblies',
    )
    op.drop_index(
        'ix_etv_assemblies_property_status_start',
        table_name='etv_assemblies',
    )
    op.drop_index(
        op.f('ix_etv_assemblies_created_by'),
        table_name='etv_assemblies',
    )
    op.drop_index(
        op.f('ix_etv_assemblies_organization_id'),
        table_name='etv_assemblies',
    )
    op.drop_index(
        op.f('ix_etv_assemblies_property_id'),
        table_name='etv_assemblies',
    )
    op.drop_table('etv_assemblies')
    # Explicit ENUM drops — Postgres keeps types around after the
    # table goes if we don't.
    sa.Enum(name='agenda_item_vote_result').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='agenda_item_type').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='assembly_status').drop(op.get_bind(), checkfirst=False)
