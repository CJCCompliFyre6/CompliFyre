"""add clause_checklist_review table

Revision ID: 844f14126673
Revises: c1854e1d3f6c
Create Date: 2026-09-16 16:23:50.061190

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '844f14126673'
down_revision = 'c1854e1d3f6c'
branch_labels = None
depends_on = None


def upgrade():
    # Build Sequence #TBD: new table for Part C, Step C6 (Clause-level
    # checklist assurance review) -- a single LLM call, run once every
    # sibling activity's checklist under a clause exists and cross-sibling
    # dependency resolution (#398) has already run, produces:
    #   (a) sufficiency verdict + reasoning for the clause as a whole
    #   (c) candidate duplicate-item pairs across sibling activities
    #       (candidates only -- C8, not yet built, persists CONFIRMED
    #       links permanently once C6/C7 settle)
    # `iteration` supports C7's regenerate-once-then-flag loop (not yet
    # built) -- multiple rows per clause_id once that orchestration exists.
    op.create_table(
        'clause_checklist_review',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('clause_id', sa.Integer(), nullable=False),
        sa.Column('iteration', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('sufficiency_verdict', sa.String(length=20), nullable=False),
        sa.Column('sufficiency_reasoning', sa.Text(), nullable=True),
        sa.Column('duplicate_pairs_json', sa.JSON(), nullable=True),
        sa.Column('raw_output_json', sa.JSON(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['clause_id'], ['clauses.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('clause_checklist_review')
