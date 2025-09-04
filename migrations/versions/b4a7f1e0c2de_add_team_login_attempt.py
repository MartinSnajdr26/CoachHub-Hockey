"""add team_login_attempt table

Revision ID: b4a7f1e0c2de
Revises: 9d1ef2a7c0c3
Create Date: 2025-09-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = 'b4a7f1e0c2de'
down_revision = '9d1ef2a7c0c3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'team_login_attempt',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('team.id'), nullable=False),
        sa.Column('ip_truncated', sa.String(length=50), nullable=False),
        sa.Column('window_start', sa.DateTime(), nullable=True),
        sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
    )
    op.create_index('ix_tla_team_ip', 'team_login_attempt', ['team_id', 'ip_truncated'])


def downgrade():
    op.drop_index('ix_tla_team_ip', table_name='team_login_attempt')
    op.drop_table('team_login_attempt')

