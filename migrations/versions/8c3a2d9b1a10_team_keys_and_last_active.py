"""add team.last_active_at and team_key table

Revision ID: 8c3a2d9b1a10
Revises: 7b2a1c1f4f1a
Create Date: 2025-09-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = '8c3a2d9b1a10'
down_revision = '7b2a1c1f4f1a'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('team') as batch_op:
        batch_op.add_column(sa.Column('last_active_at', sa.DateTime(), nullable=True))
    op.create_table(
        'team_key',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('team.id'), nullable=False, index=True),
        sa.Column('role', sa.String(length=10), nullable=False),
        sa.Column('key_hash', sa.String(length=255), nullable=False),
        sa.Column('active', sa.Boolean(), server_default=sa.text('1'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('rotated_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table('team_key')
    with op.batch_alter_table('team') as batch_op:
        batch_op.drop_column('last_active_at')

