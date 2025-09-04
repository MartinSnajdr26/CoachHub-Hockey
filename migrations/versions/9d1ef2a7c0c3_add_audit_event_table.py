"""add audit_event table

Revision ID: 9d1ef2a7c0c3
Revises: 8c3a2d9b1a10
Create Date: 2025-09-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '9d1ef2a7c0c3'
down_revision = '8c3a2d9b1a10'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'audit_event',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('event', sa.String(length=50), nullable=False),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('team.id'), nullable=True),
        sa.Column('role', sa.String(length=10), nullable=True),
        sa.Column('ip_truncated', sa.String(length=50), nullable=True),
        sa.Column('meta', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
    )
    op.create_index('ix_audit_event_team_created', 'audit_event', ['team_id', 'created_at'])


def downgrade():
    op.drop_index('ix_audit_event_team_created', table_name='audit_event')
    op.drop_table('audit_event')

