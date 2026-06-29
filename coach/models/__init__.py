from coach.extensions import db
from datetime import datetime


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
    image_data = db.Column(db.Text, nullable=True)   # base64 image
    path_data = db.Column(db.Text, nullable=True)    # JSON


class TrainingSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(300), nullable=False)
    drill_ids = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class LineupSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    primary_color = db.Column(db.String(20), nullable=True)
    secondary_color = db.Column(db.String(20), nullable=True)
    logo_path = db.Column(db.String(255), nullable=True)
    tymuj_ics_url = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_active_at = db.Column(db.DateTime, nullable=True)

    # legacy users removed in team-only mode


class AuditEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(50), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True, index=True)
    role = db.Column(db.String(10), nullable=True)
    ip_truncated = db.Column(db.String(50), nullable=True)
    meta = db.Column(db.Text, nullable=True)  # JSON string payload
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# User model removed in team-only mode


class TeamLoginAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False, index=True)
    ip_truncated = db.Column(db.String(50), nullable=False, index=True)
    window_start = db.Column(db.DateTime, nullable=True)
    attempts = db.Column(db.Integer, default=0)


class TeamKey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False, index=True)
    role = db.Column(db.String(10), nullable=False)  # 'coach' | 'player'
    key_hash = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    rotated_at = db.Column(db.DateTime, nullable=True)


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
    source = db.Column(db.String(20), nullable=False, default='coachhub_manual')  # manual|recurring|tymuj|system
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


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
    last_updated = db.Column(db.DateTime, nullable=True)       # last successful parse
    last_error = db.Column(db.String(400), nullable=True)
    last_attempt = db.Column(db.DateTime, nullable=True)       # for rate limiting
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


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
    imported_at = db.Column(db.DateTime, nullable=True)
    note = db.Column(db.String(300), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    player = db.relationship('Player')


class AttendanceImport(db.Model):
    """One Týmuj CSV/Excel attendance import batch (metadata only; the uploaded
    file is parsed in memory and never persisted)."""
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('team_id', 'year', 'month', name='uq_payment_period'),)


class PaymentStatus(db.Model):
    """One payment status per player per month. Missing row = 'unpaid'."""
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False, index=True)
    period_id = db.Column(db.Integer, db.ForeignKey('payment_period.id'), nullable=False, index=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False, index=True)
    status = db.Column(db.String(12), nullable=False, default='unpaid')  # paid|partial|unpaid
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('period_id', 'player_id', name='uq_payment_status'),)


__all__ = [
    'db', 'Player', 'Roster', 'LineAssignment', 'Drill', 'TrainingSession',
    'LineupSession', 'Team', 'AuditEvent', 'TrainingEvent', 'AttendanceEntry', 'TeamKey', 'TeamLoginAttempt',
    'LeagueIntegration', 'AttendanceImport', 'PaymentPeriod', 'PaymentStatus'
]
