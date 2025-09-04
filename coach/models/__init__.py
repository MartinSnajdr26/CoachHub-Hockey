from coach.extensions import db, bcrypt
from datetime import datetime
from flask_login import UserMixin


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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


__all__ = [
    'db', 'Player', 'Roster', 'LineAssignment', 'Drill', 'TrainingSession',
    'LineupSession', 'Team', 'AuditEvent', 'TrainingEvent', 'TeamKey', 'TeamLoginAttempt'
]
