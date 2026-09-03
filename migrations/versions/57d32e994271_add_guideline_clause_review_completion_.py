"""add guideline clause-review completion gate

Revision ID: 57d32e994271
Revises: 190a827ae2ac
Create Date: 2026-08-20 09:48:44.364667

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '57d32e994271'
down_revision = '190a827ae2ac'
branch_labels = None
depends_on = None


def upgrade():
    # Hand-scoped: autogenerate bundled unrelated pre-existing schema drift
    # (index drops, column type changes on unrelated tables) -- excluded,
    # same as the prior migration. This does ONLY the guideline review-gate columns.
    with op.batch_alter_table('guidelines', schema=None) as batch_op:
        batch_op.add_column(sa.Column('clause_review_completed_at', sa.TIMESTAMP(), nullable=True))
        batch_op.add_column(sa.Column('clause_review_completed_by', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_guidelines_clause_review_completed_by', 'Users', ['clause_review_completed_by'], ['id'])


def downgrade():
    with op.batch_alter_table('guidelines', schema=None) as batch_op:
        batch_op.drop_constraint('fk_guidelines_clause_review_completed_by', type_='foreignkey')
        batch_op.drop_column('clause_review_completed_by')
        batch_op.drop_column('clause_review_completed_at')
