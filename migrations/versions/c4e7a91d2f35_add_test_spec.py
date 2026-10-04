"""add test_mode and test_spec to control_activities (full-population testing, Phase 1)

Revision ID: c4e7a91d2f35
Revises: d5e2b8c13f60
Create Date: 2026-10-03
"""
from alembic import op
import sqlalchemy as sa

revision = "c4e7a91d2f35"
down_revision = "d5e2b8c13f60"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("control_activities", sa.Column("test_mode", sa.String(length=30), nullable=True))
    op.add_column("control_activities", sa.Column("test_spec", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("control_activities", "test_spec")
    op.drop_column("control_activities", "test_mode")
