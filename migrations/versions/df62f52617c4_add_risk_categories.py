"""add risk_categories and category_id on risk_areas

Revision ID: df62f52617c4
Revises: 6feacdf321d2
Create Date: 2026-08-31 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'df62f52617c4'
down_revision = '6feacdf321d2'
branch_labels = None
depends_on = None


def upgrade():
    # Hand-scoped: adds the top-level risk_categories table and links
    # risk_areas to it, per the two-level taxonomy confirmed with Ankita.
    # Build Sequence #372.
    op.create_table(
        'risk_categories',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    with op.batch_alter_table('risk_areas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_risk_areas_category_id', 'risk_categories', ['category_id'], ['id']
        )


def downgrade():
    with op.batch_alter_table('risk_areas', schema=None) as batch_op:
        batch_op.drop_constraint('fk_risk_areas_category_id', type_='foreignkey')
        batch_op.drop_column('category_id')
    op.drop_table('risk_categories')
