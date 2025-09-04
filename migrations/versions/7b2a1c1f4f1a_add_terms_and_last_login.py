"""add terms fields and last_login to user

Revision ID: 7b2a1c1f4f1a
Revises: 4a1b9e2f8c0a
Create Date: 2025-09-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '7b2a1c1f4f1a'
down_revision = '4a1b9e2f8c0a'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user') as batch_op:
        batch_op.add_column(sa.Column('last_login', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('terms_version', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('terms_accepted_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('user') as batch_op:
        batch_op.drop_column('terms_accepted_at')
        batch_op.drop_column('terms_version')
        batch_op.drop_column('last_login')

