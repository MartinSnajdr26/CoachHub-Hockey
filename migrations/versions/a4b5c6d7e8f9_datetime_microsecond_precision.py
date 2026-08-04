"""widen all datetime columns to DATETIME(6) on MySQL (microsecond precision)

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-07-28 00:00:00.000000

Production validation of the SQLite -> MySQL copy found that MySQL stored every
DATETIME with ZERO fractional-seconds precision, so microseconds were lost and
some values were ROUNDED to the next second, e.g.:

  team.last_active_at   SQLite 2026-07-24 18:18:36.769460 -> MySQL 18:18:37
  audit_event.created_at SQLite 2025-09-04 18:33:02.806430 -> MySQL 18:33:03

All row counts / PKs / NULLs / FKs matched; only datetime content digests failed.
MySQL's default ``DATETIME`` is ``DATETIME(0)``; rounding fractional seconds is
documented behaviour and is NOT caught by STRICT sql_mode. The fix is schema:
store ``DATETIME(6)`` so the SQLite microseconds round-trip exactly.

DIALECT-AWARE and value-preserving (no table recreation, no data rewrite):

  * MySQL  -> ALTER each datetime column to DATETIME(6) in place. The two columns
             carrying a CURRENT_TIMESTAMP server default (team_key.created_at,
             audit_event.created_at) also get CURRENT_TIMESTAMP(6), because MySQL
             requires the default's fsp to match a fractional column.
  * SQLite -> no-op. SQLite's DATETIME already stores full microseconds, so there
             is nothing to change.

Nullability and defaults are preserved exactly; timezone behaviour is unchanged
(values remain naive UTC).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = 'a4b5c6d7e8f9'
down_revision = 'f3a4b5c6d7e8'
branch_labels = None
depends_on = None

# (table, column, existing_nullable) — datetime columns WITHOUT a server default.
_PLAIN = [
    ('training_session', 'created_at', True),
    ('lineup_session', 'created_at', True),
    ('team', 'created_at', True),
    ('team', 'last_active_at', True),
    ('team_login_attempt', 'window_start', True),
    ('team_key', 'rotated_at', True),
    ('training_event', 'created_at', True),
    ('league_integration', 'last_updated', True),
    ('league_integration', 'last_attempt', True),
    ('league_integration', 'created_at', True),
    ('attendance_entry', 'imported_at', True),
    ('attendance_entry', 'updated_at', True),
    ('attendance_import', 'created_at', True),
    ('payment_period', 'created_at', True),
    ('payment_status', 'updated_at', True),
    ('team_calendar_feed_token', 'created_at', False),
    ('team_calendar_feed_token', 'rotated_at', True),
]

# Datetime columns WITH a CURRENT_TIMESTAMP server default (all nullable=True).
# Their default must move to CURRENT_TIMESTAMP(6) to stay valid on DATETIME(6).
_WITH_CTS = [
    ('team_key', 'created_at'),
    ('audit_event', 'created_at'),
]


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'mysql':
        return  # SQLite already stores microseconds -> nothing to do.
    for table, column, nullable in _PLAIN:
        op.alter_column(
            table, column,
            existing_type=sa.DateTime(),
            type_=mysql.DATETIME(fsp=6),
            existing_nullable=nullable,
        )
    for table, column in _WITH_CTS:
        op.alter_column(
            table, column,
            existing_type=sa.DateTime(),
            type_=mysql.DATETIME(fsp=6),
            existing_nullable=True,
            existing_server_default=sa.text('CURRENT_TIMESTAMP'),
            server_default=sa.text('CURRENT_TIMESTAMP(6)'),
        )


def downgrade():
    # WARNING: reverting DATETIME(6) -> DATETIME(0) DROPS fractional seconds and
    # ROUNDS some values to the next second — the exact corruption this revision
    # fixes. Only downgrade if microsecond precision is genuinely not needed.
    bind = op.get_bind()
    if bind.dialect.name != 'mysql':
        return
    for table, column in _WITH_CTS:
        op.alter_column(
            table, column,
            existing_type=mysql.DATETIME(fsp=6),
            type_=sa.DateTime(),
            existing_nullable=True,
            existing_server_default=sa.text('CURRENT_TIMESTAMP(6)'),
            server_default=sa.text('CURRENT_TIMESTAMP'),
        )
    for table, column, nullable in _PLAIN:
        op.alter_column(
            table, column,
            existing_type=mysql.DATETIME(fsp=6),
            type_=sa.DateTime(),
            existing_nullable=nullable,
        )
