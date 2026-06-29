"""Attendance provenance columns + attendance_import batch table.

Additive only (safe): adds source/source_detail/updated_by_role/imported_at/note
to attendance_entry and creates the attendance_import table. CoachHub-first
attendance with Týmuj CSV/Excel import.

Revision ID: a7c1d2e3f4b5
Revises: f1a2b3c4d5e6
Create Date: 2026-06-28
"""
from alembic import op
import sqlalchemy as sa


revision = 'a7c1d2e3f4b5'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('attendance_entry') as batch:
        batch.add_column(sa.Column('source', sa.String(length=20), nullable=False,
                                   server_default='system'))
        batch.add_column(sa.Column('source_detail', sa.String(length=60), nullable=True))
        batch.add_column(sa.Column('updated_by_role', sa.String(length=10), nullable=True))
        batch.add_column(sa.Column('imported_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('note', sa.String(length=300), nullable=True))
    op.create_index('ix_attendance_entry_source', 'attendance_entry', ['source'])

    op.create_table(
        'attendance_import',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('team.id'), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('created_by_role', sa.String(length=10), nullable=True),
        sa.Column('source', sa.String(length=20), nullable=False, server_default='tymuj_import'),
        sa.Column('file_type', sa.String(length=10), nullable=True),
        sa.Column('filename', sa.String(length=200), nullable=True),
        sa.Column('players_created', sa.Integer(), nullable=True),
        sa.Column('events_created', sa.Integer(), nullable=True),
        sa.Column('attendance_imported', sa.Integer(), nullable=True),
        sa.Column('skipped', sa.Integer(), nullable=True),
        sa.Column('overwritten', sa.Integer(), nullable=True),
        sa.Column('warnings', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='completed'),
    )


def downgrade():
    op.drop_table('attendance_import')
    op.drop_index('ix_attendance_entry_source', table_name='attendance_entry')
    with op.batch_alter_table('attendance_entry') as batch:
        batch.drop_column('note')
        batch.drop_column('imported_at')
        batch.drop_column('updated_by_role')
        batch.drop_column('source_detail')
        batch.drop_column('source')
