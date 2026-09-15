"""add dimension flags to control_activities

Revision ID: c1854e1d3f6c
Revises: d695ecd17b22
Create Date: 2026-09-15 07:17:01.347164

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1854e1d3f6c'
down_revision = 'd695ecd17b22'
branch_labels = None
depends_on = None


def upgrade():
    # Build Sequence #397: consolidates what were three separate, disagreeing
    # Design/Implementation/Operating decisions into one, made once at test-
    # procedure-generation time (the point with the most information --
    # control_type and frequency are decided in this same call). Stored here,
    # alongside control_type/frequency on the same record, since it's the
    # same-level decision about the same activity.
    op.add_column('control_activities', sa.Column('dimension_design', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('control_activities', sa.Column('dimension_implementation', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('control_activities', sa.Column('dimension_operating', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('control_activities', 'dimension_operating')
    op.drop_column('control_activities', 'dimension_implementation')
    op.drop_column('control_activities', 'dimension_design')
