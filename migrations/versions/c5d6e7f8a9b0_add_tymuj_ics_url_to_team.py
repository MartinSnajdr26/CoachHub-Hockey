"""add tymuj_ics_url to team

Revision ID: c5d6e7f8a9b0
Revises: 21a922b1395f
Create Date: 2026-06-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c5d6e7f8a9b0'
down_revision = '21a922b1395f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('team', sa.Column('tymuj_ics_url', sa.String(length=255), nullable=True))


def downgrade():
    op.drop_column('team', 'tymuj_ics_url')
