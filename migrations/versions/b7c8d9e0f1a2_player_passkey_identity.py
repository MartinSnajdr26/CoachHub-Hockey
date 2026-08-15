"""Player identity: registration requests + passkey credentials.

Adds the two tables behind the passkey player-identity model:

- ``player_registration_request`` — a player's PENDING claim on a roster entry,
  awaiting coach approval. ``claimed_name`` is temporary display data and is
  NULLed once the request is activated or rejected.
- ``passkey_credential`` — WebAuthn credentials bound to the opaque
  ``player_id``. Only ``status='active'`` may authenticate.

Both are NEW tables only. No existing table is altered, rebuilt or backfilled,
so this is safe on the production MySQL data: existing coach and shared-key
player logins are untouched by the schema change.

Datetimes use DATETIME(6) on MySQL to match the project-wide microsecond
convention (see migration a4b5c6d7e8f9) and plain DATETIME on SQLite.

Revision ID: b7c8d9e0f1a2
Revises: a4b5c6d7e8f9
Create Date: 2026-08-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME as MYSQL_DATETIME


revision = 'b7c8d9e0f1a2'
down_revision = 'a4b5c6d7e8f9'
branch_labels = None
depends_on = None

# Microsecond-precise datetime, portable across SQLite (dev/tests) and MySQL.
_DT6 = sa.DateTime().with_variant(MYSQL_DATETIME(fsp=6), 'mysql')


def upgrade():
    op.create_table(
        'player_registration_request',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('team.id'), nullable=False, index=True),
        sa.Column('player_id', sa.Integer(), sa.ForeignKey('player.id'), nullable=False, index=True),
        # Temporary: exists only for the coach's approval decision.
        sa.Column('claimed_name', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=12), nullable=False, server_default='pending', index=True),
        # sha256 hex of the requesting browser's claim token — never the token.
        sa.Column('claim_token_hash', sa.String(length=64), nullable=False, index=True),
        sa.Column('created_at', _DT6, nullable=False),
        sa.Column('expires_at', _DT6, nullable=False),
        sa.Column('approved_at', _DT6, nullable=True),
        sa.Column('rejected_at', _DT6, nullable=True),
        sa.Column('activated_at', _DT6, nullable=True),
    )
    # Coach inbox lookup: pending requests of one team.
    op.create_index('ix_prr_team_status', 'player_registration_request',
                    ['team_id', 'status'])

    op.create_table(
        'passkey_credential',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('team.id'), nullable=False, index=True),
        sa.Column('player_id', sa.Integer(), sa.ForeignKey('player.id'), nullable=False, index=True),
        sa.Column('role', sa.String(length=10), nullable=False, server_default='player'),
        # base64url. Unique: it is the authentication-time lookup key.
        sa.Column('credential_id', sa.String(length=255), nullable=False),
        sa.Column('public_key', sa.Text(), nullable=False),
        sa.Column('sign_count', sa.Integer(), nullable=False, server_default='0'),
        # Opaque random per-player WebAuthn user handle (base64url).
        sa.Column('user_handle', sa.String(length=64), nullable=False, index=True),
        sa.Column('transports', sa.String(length=120), nullable=True),
        sa.Column('device_type', sa.String(length=20), nullable=True),
        sa.Column('backed_up', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('status', sa.String(length=12), nullable=False, server_default='active', index=True),
        sa.Column('created_at', _DT6, nullable=False),
        sa.Column('last_used_at', _DT6, nullable=True),
        sa.Column('revoked_at', _DT6, nullable=True),
    )
    op.create_index('ix_passkey_credential_credential_id', 'passkey_credential',
                    ['credential_id'], unique=True)
    # "Which devices does this player still have?" — the coach access screen.
    op.create_index('ix_passkey_team_player_status', 'passkey_credential',
                    ['team_id', 'player_id', 'status'])


def downgrade():
    op.drop_index('ix_passkey_team_player_status', table_name='passkey_credential')
    op.drop_index('ix_passkey_credential_credential_id', table_name='passkey_credential')
    op.drop_table('passkey_credential')
    op.drop_index('ix_prr_team_status', table_name='player_registration_request')
    op.drop_table('player_registration_request')
