"""Add recurrence columns to training_event (Calendar 2.0).

Additive only: series_id, recurrence_rule, source.

Revision ID: b8d2e3f4a5c6
Revises: a7c1d2e3f4b5
Create Date: 2026-06-29
"""
from alembic import op
import sqlalchemy as sa


revision = 'b8d2e3f4a5c6'
down_revision = 'a7c1d2e3f4b5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('training_event') as batch:
        batch.add_column(sa.Column('series_id', sa.String(length=36), nullable=True))
        batch.add_column(sa.Column('recurrence_rule', sa.String(length=80), nullable=True))
        batch.add_column(sa.Column('source', sa.String(length=20), nullable=False,
                                   server_default='coachhub_manual'))
    op.create_index('ix_training_event_series_id', 'training_event', ['series_id'])


def downgrade():
    op.drop_index('ix_training_event_series_id', table_name='training_event')
    with op.batch_alter_table('training_event') as batch:
        batch.drop_column('source')
        batch.drop_column('recurrence_rule')
        batch.drop_column('series_id')
