"""add_raw_evidence_requirements_table

Revision ID: a697c00411bd
Revises: cb14e0281073
Create Date: 2026-09-22 09:41:35.129402

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a697c00411bd'
down_revision = 'cb14e0281073'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'raw_evidence_requirements',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('control_activity_id', sa.Integer(), nullable=False),
        sa.Column('guideline_id', sa.BigInteger(), nullable=False),
        sa.Column('clause_id', sa.BigInteger(), nullable=True),
        sa.Column('clause_no', sa.String(length=100), nullable=True),
        sa.Column('category', sa.String(length=255), nullable=True),
        sa.Column('evidence_item', sa.Text(), nullable=False),
        sa.Column('evidence_artifact_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(['control_activity_id'], ['control_activities.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['guideline_id'], ['guidelines.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_raw_evidence_requirements_control_activity_id'), 'raw_evidence_requirements', ['control_activity_id'], unique=False)
    op.create_index(op.f('ix_raw_evidence_requirements_guideline_id'), 'raw_evidence_requirements', ['guideline_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_raw_evidence_requirements_guideline_id'), table_name='raw_evidence_requirements')
    op.drop_index(op.f('ix_raw_evidence_requirements_control_activity_id'), table_name='raw_evidence_requirements')
    op.drop_table('raw_evidence_requirements')
