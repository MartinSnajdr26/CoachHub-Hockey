"""drop user and audit_log tables

Revision ID: cd3a9f4b6e21
Revises: b4a7f1e0c2de
Create Date: 2025-09-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = 'cd3a9f4b6e21'
down_revision = 'b4a7f1e0c2de'
branch_labels = None
depends_on = None


def upgrade():
    # Drop legacy tables if they exist
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if 'audit_log' in tables:
        op.drop_table('audit_log')
    if 'user' in tables:
        op.drop_table('user')


def downgrade():
    # No-op: legacy tables intentionally removed
    pass

