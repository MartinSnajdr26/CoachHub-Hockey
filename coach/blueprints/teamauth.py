from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from datetime import datetime
from coach.extensions import db
from coach.models import Team, TeamKey, AuditEvent
from coach.services.keys import hash_team_key, verify_team_key, gen_plain_key

bp = Blueprint('teamauth', __name__)
limiter = Limiter(key_func=get_remote_address)


def _truncate_ip(ip: str) -> str:
    try:
        parts = ip.split('.')
        return '.'.join(parts[:3] + ['0']) if len(parts) == 4 else ip
    except Exception:
        return ip


@bp.route('/team/auth', methods=['GET'])
def team_auth():
    teams = Team.query.order_by(Team.name.asc()).all()
    return render_template('team_auth.html', teams=teams, terms_version=current_app.config.get('TERMS_VERSION', 'v1.0'))


@bp.route('/team/login', methods=['POST'])
@limiter.limit('5 per minute')
def team_login():
    team_id = request.form.get('team_id')
    role = (request.form.get('role') or 'player').strip()
    key = request.form.get('key') or ''
    if request.form.get('terms_accept') != 'on':
        flash('Je nutné souhlasit s Podmínkami používání.', 'error')
        return redirect(url_for('teamauth.team_auth'))
    team = None
    try:
        team = Team.query.get(int(team_id))
    except Exception:
        pass
    if not team or role not in ('coach','player') or not key:
        return redirect(url_for('teamauth.team_auth'))
    # Lockout check: 10 failed attempts per 30 min per team+IP
    from coach.models import TeamLoginAttempt
    ipt = _truncate_ip(request.remote_addr or '-')
    now = datetime.utcnow()
    window_minutes = 30
    attempt = None
    try:
        attempt = TeamLoginAttempt.query.filter_by(team_id=team.id, ip_truncated=ipt).first()
        if attempt and attempt.window_start and (now - attempt.window_start).total_seconds() < window_minutes*60 and attempt.attempts >= 10:
            flash('Příliš mnoho pokusů. Zkuste to za 30 minut.', 'error')
            return redirect(url_for('teamauth.team_auth'))
    except Exception:
        # Lockout table may not exist yet (migrations not applied) – continue without lockout
        attempt = None
    tk = TeamKey.query.filter_by(team_id=team.id, role=role, active=True).order_by(TeamKey.created_at.desc()).first()
    if not tk or not verify_team_key(key, tk.key_hash):
        # TODO: lockout counting table if needed
        # increment attempts
        try:
            if attempt is not None:
                if (attempt.window_start is None) or ((now - attempt.window_start).total_seconds() >= window_minutes*60):
                    attempt.attempts = 1
                    attempt.window_start = now
                else:
                    attempt.attempts = (attempt.attempts or 0) + 1
            else:
                # Create record only if table exists
                attempt = TeamLoginAttempt(team_id=team.id, ip_truncated=ipt, attempts=1, window_start=now)
                db.session.add(attempt)
            db.session.commit()
        except Exception:
            db.session.rollback()
        flash('Neplatný klíč.', 'error')
        return redirect(url_for('teamauth.team_auth'))
    # establish session
    session['team_id'] = team.id
    session['team_role'] = role
    session['team_login'] = True
    # reset attempts on success
    try:
        if attempt:
            attempt.attempts = 0
            db.session.commit()
    except Exception:
        db.session.rollback()
    try:
        team.last_active_at = datetime.utcnow()
        db.session.commit()
    except Exception:
        db.session.rollback()
    # log minimal audit (legacy AuditLog if present)
    try:
        ipt = _truncate_ip(request.remote_addr or '-')
        tv = current_app.config.get('TERMS_VERSION', 'v1.0')
        db.session.add(AuditEvent(event='team.login', team_id=team.id, role=role, ip_truncated=ipt, meta='{}'))
        db.session.add(AuditEvent(event='terms.accepted', team_id=team.id, role=role, ip_truncated=ipt, meta=f"{{\"version\":\"{tv}\"}}"))
        db.session.commit()
    except Exception:
        db.session.rollback()
    return redirect(url_for('home'))


@bp.route('/team/logout')
def team_logout():
    session.pop('team_id', None)
    session.pop('team_role', None)
    session.pop('team_login', None)
    return redirect(url_for('teamauth.team_auth'))


@bp.route('/team/create', methods=['POST'])
def team_create():
    name = (request.form.get('team_name') or '').strip()
    if request.form.get('terms_accept') != 'on' or not name:
        flash('Vyplň název a potvrď podmínky.', 'error')
        return redirect(url_for('teamauth.team_auth'))
    # create team
    t = Team(name=name)
    # optional brand
    prim = (request.form.get('primary_color') or '').strip()
    sec = (request.form.get('secondary_color') or '').strip()
    if prim:
        t.primary_color = prim
    if sec:
        t.secondary_color = sec
    db.session.add(t); db.session.flush()
    # optional logo
    logo_f = request.files.get('team_logo')
    if logo_f and getattr(logo_f, 'filename', ''):
        try:
            from coach.app import _save_logo_file
            err, rel = _save_logo_file(logo_f)
            if not err and rel:
                t.logo_path = rel
        except Exception:
            pass
    coach_plain = gen_plain_key()
    player_plain = gen_plain_key()
    db.session.add(TeamKey(team_id=t.id, role='coach', key_hash=hash_team_key(coach_plain)))
    db.session.add(TeamKey(team_id=t.id, role='player', key_hash=hash_team_key(player_plain)))
    db.session.commit()
    # log audit
    try:
        tv = current_app.config.get('TERMS_VERSION', 'v1.0')
        ipt = _truncate_ip(request.remote_addr or '-')
        db.session.add(AuditEvent(event='team.created', team_id=t.id, role='coach', ip_truncated=ipt, meta='{}'))
        db.session.add(AuditEvent(event='terms.accepted', team_id=t.id, role='coach', ip_truncated=ipt, meta=f"{{\"version\":\"{tv}\"}}"))
        db.session.commit()
    except Exception:
        db.session.rollback()
    # Show keys once
    return render_template('team_create_result.html', team=t, coach_key=coach_plain, player_key=player_plain)


@bp.route('/team/keys', methods=['GET', 'POST'])
def team_keys():
    team_id = session.get('team_id'); role = session.get('team_role')
    if not (team_id and role == 'coach'):
        return redirect(url_for('teamauth.team_auth'))
    team = Team.query.get(team_id)
    if request.method == 'POST':
        which = request.form.get('which')
        if which in ('coach','player'):
            # rotate
            now = datetime.utcnow()
            TeamKey.query.filter_by(team_id=team.id, role=which, active=True).update({TeamKey.active: False, TeamKey.rotated_at: now})
            new_plain = gen_plain_key()
            db.session.add(TeamKey(team_id=team.id, role=which, key_hash=hash_team_key(new_plain), active=True))
            db.session.commit()
            try:
                db.session.add(AuditEvent(event='team.key_rotated', team_id=team.id, role='coach', ip_truncated=_truncate_ip(request.remote_addr or '-'), meta=f"{{\"role\":\"{which}\"}}"))
                db.session.commit()
            except Exception:
                db.session.rollback()
            flash(f'Nový klíč ({which}) byl vygenerován. Ulož si ho – ukáže se jen jednou.', 'info')
            return render_template('team_keys.html', team=team, rotated_role=which, rotated_plain=new_plain, keys=TeamKey.query.filter_by(team_id=team.id).order_by(TeamKey.role.asc(), TeamKey.created_at.desc()).all())
    keys = TeamKey.query.filter_by(team_id=team.id).order_by(TeamKey.role.asc(), TeamKey.created_at.desc()).all()
    return render_template('team_keys.html', team=team, keys=keys)
