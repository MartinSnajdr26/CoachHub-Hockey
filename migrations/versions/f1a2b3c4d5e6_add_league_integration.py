"""add league_integration table

Revision ID: f1a2b3c4d5e6
Revises: ef7a3b2f9d11
Create Date: 2026-06-28
"""
from alembic import op
import sqlalchemy as sa

revision = 'f1a2b3c4d5e6'
down_revision = 'ef7a3b2f9d11'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'league_integration',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('team.id'), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=True),
        sa.Column('source_url', sa.String(length=500), nullable=True),
        sa.Column('connector', sa.String(length=30), nullable=True),
        sa.Column('highlight_team', sa.String(length=120), nullable=True),
        sa.Column('resolved_team', sa.String(length=120), nullable=True),
        sa.Column('data_json', sa.Text(), nullable=True),
        sa.Column('last_updated', sa.DateTime(), nullable=True),
        sa.Column('last_error', sa.String(length=400), nullable=True),
        sa.Column('last_attempt', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_league_integration_team_id', 'league_integration', ['team_id'], unique=True)


def downgrade():
    op.drop_index('ix_league_integration_team_id', table_name='league_integration')
    op.drop_table('league_integration')
