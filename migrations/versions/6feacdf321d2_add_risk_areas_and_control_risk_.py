"""add risk_areas and control_risk_mappings for RCM

Revision ID: 6feacdf321d2
Revises: 57d32e994271
Create Date: 2026-08-31 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '6feacdf321d2'
down_revision = '57d32e994271'
branch_labels = None
depends_on = None


def upgrade():
    # Hand-scoped: creates only the two new tables for the RCM (Risk Control
    # Matrix) feature -- standard risk-area library plus its many-to-many
    # mapping to control_activities. Build Sequence #372.
    op.create_table(
        'risk_areas',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_table(
        'control_risk_mappings',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('control_activity_id', sa.BigInteger(), nullable=False),
        sa.Column('risk_area_id', sa.Integer(), nullable=False),
        sa.Column('rationale', sa.Text(), nullable=True),
        sa.Column('generated_at', sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['control_activity_id'], ['control_activities.id']),
        sa.ForeignKeyConstraint(['risk_area_id'], ['risk_areas.id']),
        sa.UniqueConstraint('control_activity_id', 'risk_area_id', name='uq_control_risk_mapping'),
    )


def downgrade():
    op.drop_table('control_risk_mappings')
    op.drop_table('risk_areas')
