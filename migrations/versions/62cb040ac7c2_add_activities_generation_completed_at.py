"""add_activities_generation_completed_at

Revision ID: 62cb040ac7c2
Revises: a39b0131b24a
Create Date: 2026-09-20 06:58:54.097871

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '62cb040ac7c2'
down_revision = 'a39b0131b24a'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'guidelines',
        sa.Column('activities_generation_completed_at', sa.TIMESTAMP(), nullable=True)
    )


def downgrade():
    op.drop_column('guidelines', 'activities_generation_completed_at')
