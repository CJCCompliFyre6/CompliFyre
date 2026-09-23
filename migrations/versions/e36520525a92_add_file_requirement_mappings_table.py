"""add_file_requirement_mappings_table

Revision ID: e36520525a92
Revises: b66138edbfc9
Create Date: 2026-09-23 06:06:31.062880

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e36520525a92'
down_revision = 'b66138edbfc9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'file_requirement_mappings',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('project_evidence_file_id', sa.BigInteger(), nullable=False),
        sa.Column('guideline_evidence_requirement_id', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='confirmed'),
        sa.Column('mapping_mechanism', sa.String(length=100), nullable=True),
        sa.Column('mapping_reasoning', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(['project_evidence_file_id'], ['project_evidence_files.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['guideline_evidence_requirement_id'], ['guideline_evidence_requirements.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_evidence_file_id', 'guideline_evidence_requirement_id', name='uq_file_requirement_mapping'),
    )
    op.create_index(op.f('ix_file_requirement_mappings_project_evidence_file_id'), 'file_requirement_mappings', ['project_evidence_file_id'], unique=False)
    op.create_index(op.f('ix_file_requirement_mappings_guideline_evidence_requirement_id'), 'file_requirement_mappings', ['guideline_evidence_requirement_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_file_requirement_mappings_guideline_evidence_requirement_id'), table_name='file_requirement_mappings')
    op.drop_index(op.f('ix_file_requirement_mappings_project_evidence_file_id'), table_name='file_requirement_mappings')
    op.drop_table('file_requirement_mappings')
