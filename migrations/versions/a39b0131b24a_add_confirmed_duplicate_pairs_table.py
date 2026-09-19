"""add confirmed_duplicate_pairs table

Revision ID: a39b0131b24a
Revises: 844f14126673
Create Date: 2026-09-17 12:08:11.761805

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a39b0131b24a'
down_revision = '844f14126673'
branch_labels = None
depends_on = None


def upgrade():
    # Build Sequence #TBD -- C8: permanent, durable record of CONFIRMED genuine
    # duplicate checklist-item pairs across sibling activities under a clause.
    # Distinct from ClauseChecklistReview.duplicate_pairs_json, which is a
    # per-review CANDIDATE snapshot -- this table only holds pairs that have
    # been automatically confirmed (see promotion logic in eve_tasks.py):
    #   - a pair that survives from iteration=1 into iteration=2 unchanged
    #     after a C7 patch-and-recheck cycle, or
    #   - a pair found on a straight-SUFFICIENT iteration=1 review (no C7
    #     cycle occurs, so there is no second review to confirm against --
    #     promoted immediately).
    #
    # Function once confirmed: merge for evidence review (Part E, not yet
    # built) -- both checklist items stay visible/active, but evidence
    # submitted against one is treated as also satisfying the other.
    #
    # control_activity_id_a/b and checklist_item_id_a/b are ALWAYS normalized
    # at write time so control_activity_id_a < control_activity_id_b -- this
    # makes the same real pair detectable regardless of which side the LLM's
    # duplicate_pairs output happened to list first on any given review, and
    # lets the unique constraint below actually prevent double-promotion of
    # the same pair across separate pipeline runs over the clause's lifetime.
    op.create_table(
        'confirmed_duplicate_pairs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('clause_id', sa.Integer(), nullable=False),
        sa.Column('control_activity_id_a', sa.Integer(), nullable=False),
        sa.Column('checklist_item_id_a', sa.String(length=50), nullable=False),
        sa.Column('control_activity_id_b', sa.Integer(), nullable=False),
        sa.Column('checklist_item_id_b', sa.String(length=50), nullable=False),
        sa.Column('justification', sa.Text(), nullable=True),
        sa.Column('source_review_id', sa.BigInteger(), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['clause_id'], ['clauses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_review_id'], ['clause_checklist_review.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'clause_id', 'control_activity_id_a', 'checklist_item_id_a',
            'control_activity_id_b', 'checklist_item_id_b',
            name='uq_confirmed_duplicate_pair',
        ),
    )


def downgrade():
    op.drop_table('confirmed_duplicate_pairs')
