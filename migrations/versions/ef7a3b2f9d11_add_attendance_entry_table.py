"""add attendance entry table

Revision ID: ef7a3b2f9d11
Revises: c5d6e7f8a9b0
Create Date: 2026-06-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'ef7a3b2f9d11'
down_revision = 'c5d6e7f8a9b0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'attendance_entry',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('team_id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('event_key', sa.String(length=120), nullable=False),
        sa.Column('event_title', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('event_day', sa.Date(), nullable=False),
        sa.Column('event_time', sa.String(length=10), nullable=True),
        sa.Column('event_kind', sa.String(length=20), nullable=True),
        sa.Column('event_source', sa.String(length=20), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='unknown'),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_attendance_entry_event_key'), 'attendance_entry', ['event_key'], unique=False)
    op.create_index(op.f('ix_attendance_entry_player_id'), 'attendance_entry', ['player_id'], unique=False)
    op.create_index(op.f('ix_attendance_entry_team_id'), 'attendance_entry', ['team_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_attendance_entry_team_id'), table_name='attendance_entry')
    op.drop_index(op.f('ix_attendance_entry_player_id'), table_name='attendance_entry')
    op.drop_index(op.f('ix_attendance_entry_event_key'), table_name='attendance_entry')
    op.drop_table('attendance_entry')
