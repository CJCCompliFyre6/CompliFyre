"""add design_parameters_json and de_discovery_completed to eve_control_result

Revision ID: d695ecd17b22
Revises: df62f52617c4
Create Date: 2026-09-13 08:25:55.636369

Note: hand-edited after autogenerate. The auto-generated version bundled in
many unrelated changes (12+ index drops, 3 lossy type-narrowing changes on
clauses.flag_reason / compliance_activities.frequency / project_compliance_
activities.frequency, and a NOT NULL tightening on relevant_departments_id)
accumulated from other, parallel work not part of this change. Those are
each individually risky (index drops hurt query performance; the type
narrowings can silently truncate real, longer existing data -- flag_reason
values longer than 200 chars were directly observed the same day) and none
of them belong in a migration whose actual purpose is two new, additive,
nullable-safe columns. This migration is scoped to exactly that.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd695ecd17b22'
down_revision = 'df62f52617c4'
branch_labels = None
depends_on = None


def upgrade():
    # S-fix: op.batch_alter_table() is SQLite-oriented (table recreation
    # for engines with limited ALTER TABLE support) and is not needed on
    # PostgreSQL. Using it here triggered an Alembic/SQLAlchemy internal
    # code path that referenced an unrelated table's sequence
    # ("compliance_activities_id_seq" instead of
    # eve_control_result_id_seq), causing UndefinedTable on production.
    # Plain add_column/drop_column are safe, standard, and Postgres-native.
    op.add_column('eve_control_result', sa.Column('design_parameters_json', sa.JSON(), nullable=True))
    op.add_column('eve_control_result', sa.Column('de_discovery_completed', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('eve_control_result', 'de_discovery_completed')
    op.drop_column('eve_control_result', 'design_parameters_json')
