"""widen drill.image_data and drill.path_data to MEDIUMTEXT on MySQL

Revision ID: e2f3a4b5c6d7
Revises: d1f2a3b4c5e6
Create Date: 2026-07-28 00:00:00.000000

The production dry run for the SQLite -> MySQL migration found Drill payloads
that exceed MySQL's TEXT capacity (65,535 bytes):

  * drill.image_data  — up to ~381 KB (base64 snapshot of the drill diagram)
  * drill.path_data   — up to ~117 KB (JSON animation path data)

Both columns must be MEDIUMTEXT (up to ~16 MB) on MySQL before data can be
copied. This revision is DIALECT-AWARE:

  * MySQL  -> ALTER the two columns to MEDIUMTEXT in place (data preserved,
             nullability preserved, the `drill` table is NOT dropped/recreated).
  * SQLite -> no-op. SQLite's TEXT is unbounded and untyped, so there is nothing
             to change; guarding by dialect keeps `flask db upgrade` and any
             test run against SQLite clean (no batch ALTER required).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = 'e2f3a4b5c6d7'
down_revision = 'd1f2a3b4c5e6'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'mysql':
        # SQLite (and any non-MySQL): TEXT is already unbounded -> nothing to do.
        return
    op.alter_column(
        'drill', 'image_data',
        existing_type=sa.Text(),
        type_=mysql.MEDIUMTEXT(),
        existing_nullable=True,
    )
    op.alter_column(
        'drill', 'path_data',
        existing_type=sa.Text(),
        type_=mysql.MEDIUMTEXT(),
        existing_nullable=True,
    )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'mysql':
        return
    # WARNING: reverting MEDIUMTEXT -> TEXT re-imposes the 65,535-byte limit.
    # Production holds values well above that (image_data up to ~381 KB), so this
    # downgrade WILL FAIL or SILENTLY TRUNCATE those rows depending on MySQL's
    # strict-mode setting. Only run this downgrade after confirming every
    # image_data / path_data value fits in TEXT, or accept the data loss.
    op.alter_column(
        'drill', 'path_data',
        existing_type=mysql.MEDIUMTEXT(),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        'drill', 'image_data',
        existing_type=mysql.MEDIUMTEXT(),
        type_=sa.Text(),
        existing_nullable=True,
    )
