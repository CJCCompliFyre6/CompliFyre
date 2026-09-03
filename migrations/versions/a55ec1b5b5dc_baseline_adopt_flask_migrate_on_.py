"""baseline - adopt Flask-Migrate on existing live schema, no changes

Revision ID: a55ec1b5b5dc
Revises: 
Create Date: 2026-08-18 10:46:54.224833

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a55ec1b5b5dc'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
