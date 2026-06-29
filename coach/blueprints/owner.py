import os
import platform
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from sqlalchemy import text

from coach.extensions import db
from coach.models import AuditEvent, LeagueIntegration, Team
from coach.services import tymuj as tymuj_svc
from coach.services.db_state import has_table, is_database_not_ready_error, log_db_not_ready_once
from coach.services.owner_admin import get_owner_secret

bp = Blueprint('owner', __name__, url_prefix='/owner')


def _owner_secret():
    return get_owner_secret(current_app)


def _is_owner():
    return bool(session.get('owner_admin')) and bool(_owner_secret())


def owner_required(fn):
    def _wrap(*args, **kwargs):
        if _is_owner():
            return fn(*args, **kwargs)
        return redirect(url_for('owner.login', next=request.path))
    _wrap.__name__ = fn.__name__
    return _wrap


@bp.route('/login', methods=['GET', 'POST'], endpoint='login')
def login():
    secret = _owner_secret()
    if not secret:
        return ('Owner admin is not configured.', 404)
    if request.method == 'POST':
        if (request.form.get('owner_key') or '') == secret:
            session['owner_admin'] = True
            return redirect(request.args.get('next') or url_for('owner.dashboard'))
        flash('Neplatný owner klíč.', 'error')
    if _is_owner():
        return redirect(url_for('owner.dashboard'))
    return render_template('owner_login.html')


@bp.route('', methods=['POST'], endpoint='login_legacy')
def login_legacy():
    return login()


@bp.route('/logout', endpoint='logout')
def logout():
    session.pop('owner_admin', None)
    return redirect(url_for('owner.login'))


@bp.route('', endpoint='dashboard')
@owner_required
def dashboard():
    errors = _events(['app.exception', 'integration.league.failure', 'integration.tymuj.failure'], 20)
    integrations = _integration_rows()
    health = _health()
    return render_template('owner_dashboard.html', errors=errors, integrations=integrations, health=health)


@bp.route('/dashboard', endpoint='dashboard_legacy')
@owner_required
def dashboard_legacy():
    return redirect(url_for('owner.dashboard'))


@bp.route('/errors', endpoint='errors')
@owner_required
def errors():
    return render_template('owner_errors.html', events=_events(None, 100))


@bp.route('/integrations', endpoint='integrations')
@owner_required
def integrations():
    return render_template('owner_integrations.html', rows=_integration_rows())


@bp.route('/health', endpoint='health')
@owner_required
def health():
    return render_template('owner_health.html', health=_health(), rows=_integration_rows())


@bp.route('/league-debug', methods=['GET', 'POST'], endpoint='league_debug')
@owner_required
def league_debug():
    from coach.services.league import service as league_svc
    trace = None
    selected_team_id = None
    if request.method == 'POST':
        try:
            selected_team_id = int(request.form.get('team_id') or 0)
        except (TypeError, ValueError):
            selected_team_id = None
        if selected_team_id:
            ok, msg, trace = league_svc.diagnostic_refresh(selected_team_id)
            flash(msg, 'success' if ok else 'error')
    rows = league_svc.league_debug_rows()
    return render_template('owner_league_debug.html', rows=rows, trace=trace, selected_team_id=selected_team_id)


@bp.route('/tymuj-debug', methods=['GET', 'POST'], endpoint='tymuj_debug')
@owner_required
def tymuj_debug():
    trace = None
    selected_team_id = None
    if request.method == 'POST':
        try:
            selected_team_id = int(request.form.get('team_id') or 0)
        except (TypeError, ValueError):
            selected_team_id = None
        if selected_team_id:
            ok, msg, trace = tymuj_svc.diagnostic_refresh(selected_team_id)
            flash(msg, 'success' if ok else 'error')
    rows = tymuj_svc.tymuj_debug_rows()
    return render_template('owner_tymuj_debug.html', rows=rows, trace=trace, selected_team_id=selected_team_id)


@bp.route('/attendance', endpoint='attendance')
@owner_required
def attendance():
    import json as _json
    from datetime import date as _date
    from coach.services import attendance_import as ai
    from coach.models import AttendanceImport, TrainingEvent
    # Recurrence diagnostics (Calendar 2.0) — minimal
    try:
        recurrence = {
            'series': db.session.query(TrainingEvent.series_id)
                        .filter(TrainingEvent.series_id.isnot(None)).distinct().count(),
            'occurrences': TrainingEvent.query.filter(TrainingEvent.series_id.isnot(None)).count(),
            'future': TrainingEvent.query.filter(TrainingEvent.series_id.isnot(None),
                                                 TrainingEvent.day >= _date.today()).count(),
        }
    except Exception:
        db.session.rollback()
        recurrence = {'series': 0, 'occurrences': 0, 'future': 0}
    global_breakdown = ai.source_breakdown()
    teams = Team.query.order_by(Team.name.asc()).all()
    per_team = []
    for t in teams:
        bd = ai.source_breakdown(t.id)
        if any(bd.values()):
            per_team.append({'team': t, 'breakdown': bd})
    imports = (AttendanceImport.query.order_by(AttendanceImport.created_at.desc()).limit(50).all())
    team_names = {t.id: t.name for t in teams}
    rows = []
    for b in imports:
        try:
            warns = _json.loads(b.warnings or '[]')
        except Exception:
            warns = []
        rows.append({'b': b, 'team_name': team_names.get(b.team_id, 'Team #%s' % b.team_id), 'warnings': warns})
    return render_template('owner_attendance.html', global_breakdown=global_breakdown,
                           per_team=per_team, imports=rows, source_labels=ai.SOURCE_LABELS,
                           recurrence=recurrence)


def _events(names, limit):
    try:
        q = AuditEvent.query
        if names:
            q = q.filter(AuditEvent.event.in_(names))
        return q.order_by(AuditEvent.created_at.desc()).limit(limit).all()
    except Exception as exc:
        db.session.rollback()
        if not is_database_not_ready_error(exc):
            raise
        log_db_not_ready_once(current_app, 'owner-events-db-not-ready', exc, 'Owner events database is not ready')
        return []


def _integration_rows():
    try:
        teams = Team.query.order_by(Team.name.asc()).all()
        league_by_team = {li.team_id: li for li in LeagueIntegration.query.all()}
    except Exception as exc:
        db.session.rollback()
        if not is_database_not_ready_error(exc):
            raise
        log_db_not_ready_once(current_app, 'owner-integrations-db-not-ready', exc, 'Owner integrations database is not ready')
        return []
    rows = []
    for team in teams:
        li = league_by_team.get(team.id)
        ts = tymuj_svc.get_status(team.id)
        rows.append({'team': team, 'league': li, 'tymuj': ts})
    return rows


def _age_state(dt):
    if not dt:
        return 'failing'
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except Exception:
            return 'warning'
    age = datetime.utcnow() - dt
    if age > timedelta(days=7):
        return 'warning'
    return 'ok'


def _health():
    db_ok = True
    schema_ok = True
    try:
        db.session.execute(text('SELECT 1'))
        schema_ok = has_table('team')
    except Exception:
        db.session.rollback()
        db_ok = False
        schema_ok = False
    rows = _integration_rows()
    league_failures = [r for r in rows if r['league'] and r['league'].last_error]
    tymuj_failures = [r for r in rows if r['tymuj'].get('last_error')]
    league_stale = [
        r for r in rows
        if r['league'] and r['league'].enabled and not r['league'].last_error
        and _age_state(r['league'].last_updated) != 'ok'
    ]
    tymuj_stale = [
        r for r in rows
        if r['team'].tymuj_ics_url and not r['tymuj'].get('last_error')
        and _age_state(r['tymuj'].get('updated_at')) != 'ok'
    ]
    return {
        'app': {'state': 'ok', 'label': 'App OK'},
        'database': {
            'state': 'ok' if db_ok and schema_ok else 'failing',
            'label': 'Database OK' if db_ok and schema_ok else ('Database missing migrations' if db_ok else 'Database failing'),
        },
        'league': {
            'state': 'failing' if league_failures else ('warning' if league_stale else 'ok'),
            'label': 'League failing' if league_failures else ('League stale' if league_stale else 'League OK'),
        },
        'tymuj': {
            'state': 'failing' if tymuj_failures else ('warning' if tymuj_stale else 'ok'),
            'label': 'Týmuj failing' if tymuj_failures else ('Týmuj stale' if tymuj_stale else 'Týmuj OK'),
        },
        'whatsapp': {'state': 'ok', 'label': 'WhatsApp OK, local-only'},
        'cache': {
            'state': 'warning' if league_stale or tymuj_stale else 'ok',
            'label': 'Cache stale' if league_stale or tymuj_stale else 'Cache OK',
        },
        'scheduler': {'state': 'warning', 'label': 'Scheduler Status (future)'},
        'version': current_app.config.get('APP_VERSION') or os.getenv('APP_VERSION') or os.getenv('GIT_SHA') or 'dev',
        'env': current_app.config.get('ENV') or os.getenv('APP_ENV') or os.getenv('FLASK_ENV') or 'unknown',
        'python': platform.python_version(),
    }
