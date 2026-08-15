from coach.extensions import db
from datetime import datetime
from sqlalchemy.dialects.mysql import MEDIUMTEXT, DATETIME as _MYSQL_DATETIME

# Portable large-text type: plain TEXT on SQLite (dev/tests), MEDIUMTEXT on
# MySQL (up to 16 MB). Needed because Drill.image_data holds base64 snapshots
# that exceed MySQL's 64 KB TEXT limit; on SQLite this compiles to normal TEXT.
_LARGE_TEXT = db.Text().with_variant(MEDIUMTEXT(), 'mysql')

# Portable microsecond-precise datetime: plain DATETIME on SQLite (which already
# stores full microseconds), DATETIME(6) on MySQL. MySQL's default DATETIME has
# ZERO fractional precision and silently ROUNDS fractional seconds (e.g.
# .769460 -> next second), corrupting exact timestamps on import. fsp=6 makes the
# round-trip exact. Timezone behaviour is unchanged (naive UTC, as before).
# See migration a4b5c6d7e8f9.
_DT6 = db.DateTime().with_variant(_MYSQL_DATETIME(fsp=6), 'mysql')


class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    position = db.Column(db.String(10), nullable=False)  # F, D, G

    def __repr__(self):
        return f"<Player {self.name} ({self.position})>"


class Roster(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'))
    player = db.relationship('Player')


class LineAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'))
    slot = db.Column(db.String(10))  # e.g., L1F1, L1F2, D1-1, G1...
    player = db.relationship('Player')


class Drill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    duration = db.Column(db.Integer, nullable=True)  # minutes
    category = db.Column(db.String(50), nullable=True)
    image_data = db.Column(_LARGE_TEXT, nullable=True)   # base64 image (MEDIUMTEXT on MySQL)
    path_data = db.Column(_LARGE_TEXT, nullable=True)    # JSON (MEDIUMTEXT on MySQL)


class TrainingSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(300), nullable=False)
    drill_ids = db.Column(db.Text, nullable=True)
    created_at = db.Column(_DT6, default=datetime.utcnow)


class LineupSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(300), nullable=False)
    created_at = db.Column(_DT6, default=datetime.utcnow)


class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    primary_color = db.Column(db.String(20), nullable=True)
    secondary_color = db.Column(db.String(20), nullable=True)
    logo_path = db.Column(db.String(255), nullable=True)
    tymuj_ics_url = db.Column(db.String(255), nullable=True)
    created_at = db.Column(_DT6, default=datetime.utcnow)
    last_active_at = db.Column(_DT6, nullable=True)

    # legacy users removed in team-only mode


class AuditEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(50), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True, index=True)
    role = db.Column(db.String(10), nullable=True)
    ip_truncated = db.Column(db.String(50), nullable=True)
    meta = db.Column(db.Text, nullable=True)  # JSON string payload
    created_at = db.Column(_DT6, default=datetime.utcnow)


# User model removed in team-only mode


class TeamLoginAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False, index=True)
    ip_truncated = db.Column(db.String(50), nullable=False, index=True)
    window_start = db.Column(_DT6, nullable=True)
    attempts = db.Column(db.Integer, default=0)


class TeamKey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False, index=True)
    role = db.Column(db.String(10), nullable=False)  # 'coach' | 'player'
    key_hash = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(_DT6, default=datetime.utcnow)
    rotated_at = db.Column(_DT6, nullable=True)


class TrainingEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    day = db.Column(db.Date, nullable=False)
    time = db.Column(db.String(10), nullable=True)  # HH:MM
    title = db.Column(db.String(200), nullable=False, default='Trénink')
    kind = db.Column(db.String(20), nullable=True)  # 'training' | 'match'
    # Recurrence (Calendar 2.0): occurrences of one series share series_id.
    series_id = db.Column(db.String(36), nullable=True, index=True)
    recurrence_rule = db.Column(db.String(80), nullable=True)   # e.g. 'weekly:MO,WE'
    # Nullable: legacy rows created before this column existed carry SQL NULL,
    # which must be preserved verbatim on MySQL (not coerced to ''). New rows get
    # the Python-side default. See migration f3a4b5c6d7e8.
    source = db.Column(db.String(20), nullable=True, default='coachhub_manual')  # manual|recurring|tymuj|system
    created_at = db.Column(_DT6, default=datetime.utcnow)


class LeagueIntegration(db.Model):
    """Per-team league (vysledky.com etc.) integration config + cached data.

    GDPR: stores only the coach-provided competition URL and team-name string
    plus parsed PUBLIC league data (team names/scores/standings). No personal
    contact data. `data_json` is the normalized CompetitionData cache."""
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False, unique=True, index=True)
    enabled = db.Column(db.Boolean, default=False)
    source_url = db.Column(db.String(500), nullable=True)
    connector = db.Column(db.String(30), nullable=True)        # 'vysledky' | 'generic'
    highlight_team = db.Column(db.String(120), nullable=True)  # coach-entered name
    resolved_team = db.Column(db.String(120), nullable=True)   # confirmed exact name
    data_json = db.Column(db.Text, nullable=True)              # cached normalized data
    last_updated = db.Column(_DT6, nullable=True)       # last successful parse
    last_error = db.Column(db.String(400), nullable=True)
    last_attempt = db.Column(_DT6, nullable=True)       # for rate limiting
    created_at = db.Column(_DT6, default=datetime.utcnow)


class AttendanceEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False, index=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False, index=True)
    event_key = db.Column(db.String(120), nullable=False, index=True)
    event_title = db.Column(db.String(200), nullable=False, default='')
    event_day = db.Column(db.Date, nullable=False)
    event_time = db.Column(db.String(10), nullable=True)
    event_kind = db.Column(db.String(20), nullable=True, default='training')
    event_source = db.Column(db.String(20), nullable=True, default='local')
    status = db.Column(db.String(20), nullable=False, default='unknown')  # going|not_going|maybe|unknown
    # Provenance: who/what set this entry. Drives overwrite priority:
    # coachhub_coach > coachhub_player > tymuj_import > system.
    source = db.Column(db.String(20), nullable=False, default='system', index=True)
    source_detail = db.Column(db.String(60), nullable=True)   # e.g. import batch id
    updated_by_role = db.Column(db.String(10), nullable=True)  # 'coach' | 'player' | None
    imported_at = db.Column(_DT6, nullable=True)
    note = db.Column(db.String(300), nullable=True)
    updated_at = db.Column(_DT6, default=datetime.utcnow)

    player = db.relationship('Player')


class AttendanceImport(db.Model):
    """One Týmuj CSV/Excel attendance import batch (metadata only; the uploaded
    file is parsed in memory and never persisted)."""
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False, index=True)
    created_at = db.Column(_DT6, default=datetime.utcnow)
    created_by_role = db.Column(db.String(10), nullable=True)
    source = db.Column(db.String(20), nullable=False, default='tymuj_import')
    file_type = db.Column(db.String(10), nullable=True)        # csv | xlsx
    filename = db.Column(db.String(200), nullable=True)        # optional, display only
    players_created = db.Column(db.Integer, default=0)
    events_created = db.Column(db.Integer, default=0)
    attendance_imported = db.Column(db.Integer, default=0)
    skipped = db.Column(db.Integer, default=0)
    overwritten = db.Column(db.Integer, default=0)
    warnings = db.Column(db.Text, nullable=True)               # JSON list
    status = db.Column(db.String(20), nullable=False, default='completed')  # completed|rolled_back


class PaymentPeriod(db.Model):
    """One monthly contribution record per team (Pokladna). Amount in CZK.
    Designed so bank integration can be layered on later without UI changes."""
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)         # 1-12
    amount = db.Column(db.Integer, nullable=False, default=0)  # CZK
    created_at = db.Column(_DT6, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('team_id', 'year', 'month', name='uq_payment_period'),)


class PaymentStatus(db.Model):
    """One payment status per player per month. Missing row = 'unpaid'."""
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False, index=True)
    period_id = db.Column(db.Integer, db.ForeignKey('payment_period.id'), nullable=False, index=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False, index=True)
    status = db.Column(db.String(12), nullable=False, default='unpaid')  # paid|partial|unpaid
    updated_at = db.Column(_DT6, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('period_id', 'player_id', name='uq_payment_status'),)


class PlayerRegistrationRequest(db.Model):
    """A player's pending claim on a roster identity, awaiting coach approval.

    The shared player key proves only "I can reach this team's onboarding". It
    must never by itself establish `player_id`. A user picks a roster entry here
    and the row stays PENDING until a coach of THAT team approves it, so picking
    a name grants nothing on its own.

    `claimed_name` is TEMPORARY: it exists only so the coach can recognise which
    roster identity is being claimed. It is cleared the moment the request
    reaches a terminal state (activated or rejected) — the durable link is the
    opaque `player_id`, never the name.

    `claim_token_hash` binds the request to the browser that created it
    (sha256 of a random token held in that browser's session). Without it,
    anyone holding the shared player key could finish someone else's approved
    registration and mint a passkey for their identity.
    """
    __tablename__ = 'player_registration_request'

    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_ACTIVATED = 'activated'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False, index=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False, index=True)
    # Temporary display-only copy of the roster name. NULL after activation/rejection.
    claimed_name = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(12), nullable=False, default=STATUS_PENDING, index=True)
    # sha256 hex of the per-browser claim token (64 chars). Never the token itself.
    claim_token_hash = db.Column(db.String(64), nullable=False, index=True)
    created_at = db.Column(_DT6, nullable=False, default=datetime.utcnow)
    expires_at = db.Column(_DT6, nullable=False)
    approved_at = db.Column(_DT6, nullable=True)
    rejected_at = db.Column(_DT6, nullable=True)
    activated_at = db.Column(_DT6, nullable=True)

    player = db.relationship('Player')

    __table_args__ = (
        db.Index('ix_prr_team_status', 'team_id', 'status'),
    )


class PasskeyCredential(db.Model):
    """One WebAuthn credential (passkey) bound to an opaque internal player_id.

    The permanent authentication identity is (team_id, role, player_id) — never
    the player's name. One player may hold several active credentials (multiple
    devices, replaced phone), so there is no unique constraint on player_id.

    Only `status == 'active'` may authenticate. Revocation sets status='revoked'
    plus `revoked_at` rather than deleting the row, so a lost device's credential
    can never silently come back.
    """
    __tablename__ = 'passkey_credential'

    STATUS_PENDING = 'pending'
    STATUS_ACTIVE = 'active'
    STATUS_REVOKED = 'revoked'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False, index=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False, index=True)
    role = db.Column(db.String(10), nullable=False, default='player')
    # base64url, globally unique -> the lookup key at authentication time.
    credential_id = db.Column(db.String(255), nullable=False, unique=True, index=True)
    public_key = db.Column(db.Text, nullable=False)          # base64url COSE key
    sign_count = db.Column(db.Integer, nullable=False, default=0)
    # Opaque random per-player handle (base64url). NOT the name, NOT the raw id.
    user_handle = db.Column(db.String(64), nullable=False, index=True)
    transports = db.Column(db.String(120), nullable=True)
    device_type = db.Column(db.String(20), nullable=True)     # single_device | multi_device
    backed_up = db.Column(db.Boolean, nullable=False, default=False)
    status = db.Column(db.String(12), nullable=False, default=STATUS_ACTIVE, index=True)
    created_at = db.Column(_DT6, nullable=False, default=datetime.utcnow)
    last_used_at = db.Column(_DT6, nullable=True)
    revoked_at = db.Column(_DT6, nullable=True)

    player = db.relationship('Player')

    __table_args__ = (
        db.Index('ix_passkey_team_player_status', 'team_id', 'player_id', 'status'),
    )


class TeamCalendarFeedToken(db.Model):
    """Bearer token for a team's read-only .ics subscription feed.

    One active token per team (older ones kept inactive for audit). The token
    string itself is the secret in the feed URL, looked up directly, so it is
    stored plaintext (see calendar_feed service for rationale)."""
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False, index=True)
    token = db.Column(db.String(80), nullable=False, unique=True, index=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(_DT6, nullable=False, default=datetime.utcnow)
    rotated_at = db.Column(_DT6, nullable=True)


__all__ = [
    'db', 'Player', 'Roster', 'LineAssignment', 'Drill', 'TrainingSession',
    'LineupSession', 'Team', 'AuditEvent', 'TrainingEvent', 'AttendanceEntry', 'TeamKey', 'TeamLoginAttempt',
    'LeagueIntegration', 'AttendanceImport', 'PaymentPeriod', 'PaymentStatus', 'TeamCalendarFeedToken',
    'PlayerRegistrationRequest', 'PasskeyCredential'
]
