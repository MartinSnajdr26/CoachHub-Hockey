from functools import wraps
from flask import session, redirect, url_for, request, flash
from flask_login import current_user


def get_team_id() -> int | None:
    tid = session.get('team_id')
    if tid:
        try:
            return int(tid)
        except Exception:
            return None
    try:
        if current_user.is_authenticated and getattr(current_user, 'team_id', None):
            return int(current_user.team_id)
    except Exception:
        pass
    return None


def get_team_role() -> str:
    r = session.get('team_role')
    if r:
        return r
    try:
        if current_user.is_authenticated:
            return getattr(current_user, 'role', 'player') or 'player'
    except Exception:
        pass
    return 'player'


def team_login_required(fn):
    @wraps(fn)
    def _wrap(*args, **kwargs):
        if session.get('team_login') and session.get('team_id'):
            return fn(*args, **kwargs)
        if getattr(current_user, 'is_authenticated', False):
            return fn(*args, **kwargs)
        return redirect('/team/auth')
    return _wrap


def coach_required(fn):
    @wraps(fn)
    def _wrap(*args, **kwargs):
        role = get_team_role()
        if role == 'coach':
            return fn(*args, **kwargs)
        flash('Tuto akci může provést pouze trenér.', 'error')
        ref = request.referrer or url_for('home')
        return redirect(ref)
    return _wrap

