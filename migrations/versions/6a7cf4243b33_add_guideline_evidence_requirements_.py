"""add_guideline_evidence_requirements_table

Revision ID: 6a7cf4243b33
Revises: a697c00411bd
Create Date: 2026-09-23 03:52:35.709492

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6a7cf4243b33'
down_revision = 'a697c00411bd'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'guideline_evidence_requirements',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('guideline_id', sa.BigInteger(), nullable=False),
        sa.Column('evidence_item_name', sa.Text(), nullable=False),
        sa.Column('consolidation_source', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(['guideline_id'], ['guidelines.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guideline_id', 'evidence_item_name', name='uq_requirement_per_guideline'),
    )
    op.create_index(op.f('ix_guideline_evidence_requirements_guideline_id'), 'guideline_evidence_requirements', ['guideline_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_guideline_evidence_requirements_guideline_id'), table_name='guideline_evidence_requirements')
    op.drop_table('guideline_evidence_requirements')
