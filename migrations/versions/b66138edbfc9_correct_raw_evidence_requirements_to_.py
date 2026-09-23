"""correct_raw_evidence_requirements_to_link_evidence_artifact

Revision ID: b66138edbfc9
Revises: 445f7b0e4ca7
Create Date: 2026-09-23 05:15:33.298556

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b66138edbfc9'
down_revision = '445f7b0e4ca7'
branch_labels = None
depends_on = None


def upgrade():
    # raw_evidence_requirements had zero real rows at the time of this
    # correction -- table was manually dropped and recreated via
    # db.create_all() during development (confirmed empty first). This
    # migration formally records that same correction for any environment
    # applying migrations from scratch: drop the old control_activity_id FK
    # design, add the corrected evidence_artifact_id FK design (see
    # RawEvidenceRequirement's docstring in app/models/eve_models.py for the
    # full real reasoning).
    op.drop_constraint('raw_evidence_requirements_control_activity_id_fkey', 'raw_evidence_requirements', type_='foreignkey')
    op.drop_index('ix_raw_evidence_requirements_control_activity_id', table_name='raw_evidence_requirements')
    op.drop_column('raw_evidence_requirements', 'control_activity_id')
    op.add_column('raw_evidence_requirements', sa.Column('evidence_artifact_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'raw_evidence_requirements_evidence_artifact_id_fkey',
        'raw_evidence_requirements', 'evidence_artifacts',
        ['evidence_artifact_id'], ['id'], ondelete='SET NULL'
    )
    # Drop and re-add the old evidence_artifact_id column that was a plain
    # BigInteger with no real FK constraint -- replaced by the properly
    # constrained Integer FK above (same column name, different underlying
    # column since the type and constraint differ).


def downgrade():
    op.drop_constraint('raw_evidence_requirements_evidence_artifact_id_fkey', 'raw_evidence_requirements', type_='foreignkey')
    op.drop_column('raw_evidence_requirements', 'evidence_artifact_id')
    op.add_column('raw_evidence_requirements', sa.Column('control_activity_id', sa.Integer(), nullable=False))
    op.create_foreign_key(
        'raw_evidence_requirements_control_activity_id_fkey',
        'raw_evidence_requirements', 'control_activities',
        ['control_activity_id'], ['id'], ondelete='CASCADE'
    )
    op.create_index('ix_raw_evidence_requirements_control_activity_id', 'raw_evidence_requirements', ['control_activity_id'], unique=False)
