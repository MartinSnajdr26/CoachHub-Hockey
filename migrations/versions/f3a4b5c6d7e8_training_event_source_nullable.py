"""make training_event.source nullable (preserve legacy NULLs on MySQL)

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-07-28 00:00:00.000000

Production validation of the SQLite -> MySQL copy found that training_event.source
was declared NOT NULL (added by revision b8d2e3f4a5c6 with
server_default='coachhub_manual'), yet the live SQLite data legitimately holds 42
NULL rows (legacy events created before the column existed).

When the migration utility inserts those explicit NULLs into a NOT NULL MySQL
string column, MySQL's non-strict sql_mode SILENTLY coerces NULL -> '' (the type's
implicit default — NOT the DEFAULT clause, which only applies when the column is
omitted). That turned 42 NULLs into empty strings and failed NULL/content
validation.

Fix: the column must be NULLABLE so NULL round-trips faithfully. This revision is
DIALECT-AWARE and preserves all existing values (no data is rewritten):

  * MySQL  -> ALTER the column to allow NULL in place (server_default kept).
  * SQLite -> batch ALTER (SQLite cannot change nullability in place); the table
             is recreated with data + indexes preserved by Alembic batch mode.

The migration utility does NOT convert None to '' (it inserts SQL NULL); the fix
is purely schema nullability plus a target-side STRICT sql_mode guard added in the
utility so any future silent coercion fails loudly instead of corrupting data.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f3a4b5c6d7e8'
down_revision = 'e2f3a4b5c6d7'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'mysql':
        op.alter_column(
            'training_event', 'source',
            existing_type=sa.String(length=20),
            nullable=True,
            existing_server_default='coachhub_manual',
        )
    else:
        with op.batch_alter_table('training_event') as batch:
            batch.alter_column(
                'source',
                existing_type=sa.String(length=20),
                nullable=True,
                existing_server_default='coachhub_manual',
            )


def downgrade():
    # WARNING: re-imposing NOT NULL is unsafe if any training_event.source is NULL.
    # Under STRICT sql_mode the ALTER FAILS; under non-strict mode MySQL SILENTLY
    # coerces those NULLs to '' — the very data corruption this revision fixes.
    # Only downgrade after confirming (or backfilling) that no NULL source exists.
    bind = op.get_bind()
    if bind.dialect.name == 'mysql':
        op.alter_column(
            'training_event', 'source',
            existing_type=sa.String(length=20),
            nullable=False,
            existing_server_default='coachhub_manual',
        )
    else:
        with op.batch_alter_table('training_event') as batch:
            batch.alter_column(
                'source',
                existing_type=sa.String(length=20),
                nullable=False,
                existing_server_default='coachhub_manual',
            )
