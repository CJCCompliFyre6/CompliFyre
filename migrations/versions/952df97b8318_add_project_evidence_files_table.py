"""add_project_evidence_files_table

Revision ID: 952df97b8318
Revises: 62cb040ac7c2
Create Date: 2026-09-21 09:05:29.098479

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '952df97b8318'
down_revision = '62cb040ac7c2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'project_evidence_files',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('project_id', sa.BigInteger(), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=False),
        sa.Column('original_filename', sa.String(length=500), nullable=False),
        sa.Column('storage_path', sa.String(length=1000), nullable=True),
        sa.Column('file_size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('mime_type', sa.String(length=255), nullable=True),
        sa.Column('external_reference_id', sa.String(length=500), nullable=True),
        sa.Column('mapping_status', sa.String(length=50), nullable=False, server_default='pending'),
        sa.Column('uploaded_by', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.ForeignKeyConstraint(['uploaded_by'], ['Users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_project_evidence_files_project_id'), 'project_evidence_files', ['project_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_project_evidence_files_project_id'), table_name='project_evidence_files')
    op.drop_table('project_evidence_files')
