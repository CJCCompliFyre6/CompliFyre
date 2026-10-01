"""add created_by to projects (creator-only edit access)

Revision ID: 7c3e9a1f4b20
Revises: e36520525a92
Create Date: 2026-10-01

The column was first added directly on the HDB instance; IF NOT EXISTS keeps
this migration safe to run there as well as on any other instance.
"""
from alembic import op


revision = "7c3e9a1f4b20"
down_revision = "e36520525a92"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        'ALTER TABLE projects ADD COLUMN IF NOT EXISTS created_by INTEGER '
        'REFERENCES "Users"(id)'
    )


def downgrade():
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS created_by")
