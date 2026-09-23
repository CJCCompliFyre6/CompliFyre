"""add_raw_to_grouped_requirement_links_table

Revision ID: 445f7b0e4ca7
Revises: 6a7cf4243b33
Create Date: 2026-09-23 04:25:15.201665

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '445f7b0e4ca7'
down_revision = '6a7cf4243b33'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'raw_to_grouped_requirement_links',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('raw_evidence_requirement_id', sa.BigInteger(), nullable=False),
        sa.Column('guideline_evidence_requirement_id', sa.BigInteger(), nullable=False),
        sa.Column('merge_mechanism', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(['raw_evidence_requirement_id'], ['raw_evidence_requirements.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['guideline_evidence_requirement_id'], ['guideline_evidence_requirements.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('raw_evidence_requirement_id', 'guideline_evidence_requirement_id', name='uq_raw_to_grouped_link'),
    )
    op.create_index(op.f('ix_raw_to_grouped_requirement_links_raw_evidence_requirement_id'), 'raw_to_grouped_requirement_links', ['raw_evidence_requirement_id'], unique=False)
    op.create_index(op.f('ix_raw_to_grouped_requirement_links_guideline_evidence_requirement_id'), 'raw_to_grouped_requirement_links', ['guideline_evidence_requirement_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_raw_to_grouped_requirement_links_guideline_evidence_requirement_id'), table_name='raw_to_grouped_requirement_links')
    op.drop_index(op.f('ix_raw_to_grouped_requirement_links_raw_evidence_requirement_id'), table_name='raw_to_grouped_requirement_links')
    op.drop_table('raw_to_grouped_requirement_links')
