"""add tenant ownership columns to project_evidence_artifacts (S-51)

Revision ID: 5a81feead0dd
Revises: a55ec1b5b5dc
Create Date: 2026-08-18

Adds client_organization_id and auditing_firm_id directly onto
project_evidence_artifacts, mirroring Projects.client and
Projects.auditing_firm. This lets tenant-ownership checks (S-21) become a
simple two-column comparison instead of a 5-table join, once the columns
are backfilled. Both nullable at the schema level -- 152,539 existing rows
need a separate backfill pass (all confirmed to be test/demo data, no real
client data) before these can be trusted as complete.
"""
from alembic import op
import sqlalchemy as sa

revision = '5a81feead0dd'
down_revision = 'a55ec1b5b5dc'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'project_evidence_artifacts',
        sa.Column('client_organization_id', sa.BigInteger(), nullable=True),
    )
    op.add_column(
        'project_evidence_artifacts',
        sa.Column('auditing_firm_id', sa.BigInteger(), nullable=True),
    )
    op.create_index(
        'ix_project_evidence_artifacts_client_organization_id',
        'project_evidence_artifacts',
        ['client_organization_id'],
    )
    op.create_index(
        'ix_project_evidence_artifacts_auditing_firm_id',
        'project_evidence_artifacts',
        ['auditing_firm_id'],
    )
    op.create_foreign_key(
        'fk_pea_client_organization_id',
        'project_evidence_artifacts',
        'Organizations',
        ['client_organization_id'],
        ['organization_id'],
    )
    op.create_foreign_key(
        'fk_pea_auditing_firm_id',
        'project_evidence_artifacts',
        'AuditOrganization',
        ['auditing_firm_id'],
        ['id'],
    )


def downgrade():
    op.drop_constraint('fk_pea_auditing_firm_id', 'project_evidence_artifacts', type_='foreignkey')
    op.drop_constraint('fk_pea_client_organization_id', 'project_evidence_artifacts', type_='foreignkey')
    op.drop_index('ix_project_evidence_artifacts_auditing_firm_id', table_name='project_evidence_artifacts')
    op.drop_index('ix_project_evidence_artifacts_client_organization_id', table_name='project_evidence_artifacts')
    op.drop_column('project_evidence_artifacts', 'auditing_firm_id')
    op.drop_column('project_evidence_artifacts', 'client_organization_id')
