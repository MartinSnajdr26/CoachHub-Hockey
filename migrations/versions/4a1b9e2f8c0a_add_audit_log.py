"""add audit log table

Revision ID: 4a1b9e2f8c0a
Revises: 904f4a600d32
Create Date: 2025-09-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4a1b9e2f8c0a'
down_revision = '904f4a600d32'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'audit_log',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('team.id'), nullable=True),
        sa.Column('actor_user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('target_user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
    )
    op.create_index('ix_audit_log_team_created', 'audit_log', ['team_id', 'created_at'])


def downgrade():
    op.drop_index('ix_audit_log_team_created', table_name='audit_log')
    op.drop_table('audit_log')

