"""add team calendar feed token

Revision ID: d1f2a3b4c5e6
Revises: c9e3f4a5b6d7
Create Date: 2026-07-18 00:00:00.000000

Additive only: creates the team_calendar_feed_token table. No existing tables
are altered and no data is backfilled (tokens are created lazily by the app).
"""
from alembic import op
import sqlalchemy as sa


revision = 'd1f2a3b4c5e6'
down_revision = 'c9e3f4a5b6d7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'team_calendar_feed_token',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('team_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=80), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('rotated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token', name='uq_team_calendar_feed_token_token'),
    )
    op.create_index(op.f('ix_team_calendar_feed_token_team_id'),
                    'team_calendar_feed_token', ['team_id'], unique=False)
    op.create_index(op.f('ix_team_calendar_feed_token_token'),
                    'team_calendar_feed_token', ['token'], unique=True)


def downgrade():
    op.drop_index(op.f('ix_team_calendar_feed_token_token'), table_name='team_calendar_feed_token')
    op.drop_index(op.f('ix_team_calendar_feed_token_team_id'), table_name='team_calendar_feed_token')
    op.drop_table('team_calendar_feed_token')
