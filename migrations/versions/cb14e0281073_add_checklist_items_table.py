"""add_checklist_items_table

Revision ID: cb14e0281073
Revises: 952df97b8318
Create Date: 2026-09-22 06:28:03.745934

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'cb14e0281073'
down_revision = '952df97b8318'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'checklist_items',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('control_checklist_id', sa.BigInteger(), nullable=False),
        sa.Column('item_id', sa.String(length=50), nullable=False),
        sa.Column('requirement', sa.Text(), nullable=True),
        sa.Column('full_item_json', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(['control_checklist_id'], ['control_checklist.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('control_checklist_id', 'item_id', name='uq_checklist_item_per_checklist'),
    )
    op.create_index(op.f('ix_checklist_items_control_checklist_id'), 'checklist_items', ['control_checklist_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_checklist_items_control_checklist_id'), table_name='checklist_items')
    op.drop_table('checklist_items')
