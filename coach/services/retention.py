from datetime import datetime, timedelta
from typing import Tuple
from flask import current_app
from coach.extensions import db
from coach.models import Team


def prune_inactive_users(cutoff_days: int = 365) -> Tuple[int, int]:
    """User accounts removed in team-only mode. No-op for backward compatibility."""
    return 0, 0


def prune_inactive_teams(cutoff_days: int = 365) -> Tuple[int, int]:
    """Delete teams with last_active_at older than cutoff or never active. Does not cascade user cleanup here.
    Returns (deleted_teams, deleted_files). Files deletion is not implemented (no per-team file ownership metadata).
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(days=int(cutoff_days))
    q = Team.query.filter((Team.last_active_at.is_(None)) | (Team.last_active_at < cutoff))
    teams = q.all()
    deleted_teams = 0
    for t in teams:
        try:
            # TODO: delete per-team artifacts in protected_exports if tracked
            deleted_teams += 1
            db.session.delete(t)
        except Exception:
            db.session.rollback()
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return deleted_teams, 0
