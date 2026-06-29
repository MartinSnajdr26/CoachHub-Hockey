"""Pokladna (team payments): payment_period + payment_status tables.

Revision ID: c9e3f4a5b6d7
Revises: b8d2e3f4a5c6
Create Date: 2026-06-29
"""
from alembic import op
import sqlalchemy as sa


revision = 'c9e3f4a5b6d7'
down_revision = 'b8d2e3f4a5c6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'payment_period',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('team.id'), nullable=False, index=True),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('team_id', 'year', 'month', name='uq_payment_period'),
    )
    op.create_table(
        'payment_status',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('team.id'), nullable=False, index=True),
        sa.Column('period_id', sa.Integer(), sa.ForeignKey('payment_period.id'), nullable=False, index=True),
        sa.Column('player_id', sa.Integer(), sa.ForeignKey('player.id'), nullable=False, index=True),
        sa.Column('status', sa.String(length=12), nullable=False, server_default='unpaid'),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('period_id', 'player_id', name='uq_payment_status'),
    )


def downgrade():
    op.drop_table('payment_status')
    op.drop_table('payment_period')
