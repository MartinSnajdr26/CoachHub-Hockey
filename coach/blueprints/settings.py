from flask import Blueprint, render_template, request, redirect, url_for, flash
from coach.auth_utils import team_login_required, get_team_id, coach_required
from coach.extensions import db
from coach.models import Team, AuditEvent
from coach.services.url_safety import validate_public_http_url
from coach.services.logging import log_event

bp = Blueprint('settings', __name__)


@bp.route('/settings', methods=['GET', 'POST'], endpoint='settings')
@team_login_required
def settings():
    from coach.app import _save_logo_file  # lazy imports
    # Restrict entire page to coach role
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    tid = get_team_id()
    team = Team.query.get(tid) if tid else None
    if request.method == 'POST':
        action = (request.form.get('action') or 'brand').strip()
        if action == 'brand':
            # coach-only
            resp = coach_required(lambda: None)()
            if resp is not None:
                return resp
            primary = (request.form.get('primary_color') or '').strip()
            secondary = (request.form.get('secondary_color') or '').strip()
            logo_f = request.files.get('team_logo')
            if not team:
                name = request.form.get('team_name') or 'Můj tým'
                team = Team(name=name)
                db.session.add(team)
                db.session.flush()
            if primary:
                team.primary_color = primary
            if secondary:
                team.secondary_color = secondary
            ics_url = (request.form.get('tymuj_ics_url') or '').strip()
            if ics_url:
                ok, msg = validate_public_http_url(ics_url)
                if ok:
                    team.tymuj_ics_url = ics_url
                else:
                    flash(msg, 'error')
                    log_event('integration.tymuj.invalid_url', team_id=tid, role='coach', level='warning', message=msg)
                    return redirect(url_for('settings'))
            else:
                team.tymuj_ics_url = None
            if logo_f and getattr(logo_f, 'filename', ''):
                err, rel = _save_logo_file(logo_f)
                if err:
                    flash(err, 'error')
                    return redirect(url_for('settings'))
                if rel:
                    team.logo_path = rel
            db.session.commit()
            flash('Nastavení týmu bylo uloženo.', 'success')
            try:
                db.session.add(AuditEvent(event='team.brand_update', team_id=team.id, role='coach', ip_truncated=request.remote_addr or '-', meta='{}'))
                db.session.commit()
            except Exception:
                pass
            return redirect(url_for('settings'))
        elif action == 'league_save':
            from coach.services.league import service as league_svc
            url = (request.form.get('competition_url') or '').strip()
            if url:
                ok, msg = validate_public_http_url(url)
                if not ok:
                    flash(msg, 'error')
                    log_event('integration.league.invalid_url', team_id=tid, role='coach', level='warning', message=msg)
                    return redirect(url_for('settings'))
            if bool(request.form.get('league_enabled')) and not url:
                flash('URL soutěže není vyplněná.', 'error')
                return redirect(url_for('settings'))
            league_svc.save_config(tid, bool(request.form.get('league_enabled')), url, request.form.get('highlight_team'))
            flash('Nastavení ligy bylo uloženo.', 'success')
            return redirect(url_for('settings'))
        elif action == 'tymuj_refresh':
            from coach.services import tymuj as tymuj_svc
            if not team or not team.tymuj_ics_url:
                flash('Není nastavena Týmuj ICS URL.', 'error')
                return redirect(url_for('settings'))
            ok, msg = tymuj_svc.refresh_cache(team.id, team.tymuj_ics_url)
            flash(msg, 'success' if ok else 'error')
            return redirect(url_for('settings'))
        elif action in ('league_test', 'league_refresh'):
            from coach.services.league import service as league_svc
            ok, msg = league_svc.refresh(tid, manual=True)
            flash(msg, 'success' if ok else 'error')
            return redirect(url_for('settings'))
        elif action == 'league_confirm':
            from coach.services.league import service as league_svc
            league_svc.confirm_team(tid, request.form.get('team_name'))
            flash('Tým byl potvrzen.', 'success')
            return redirect(url_for('settings'))
        elif action == 'delete_team':
            # coach-only
            resp = coach_required(lambda: None)()
            if resp is not None:
                return resp
            if not team:
                return redirect(url_for('team_auth'))
            confirm_name = (request.form.get('confirm_team_name') or '').strip()
            if confirm_name != team.name:
                flash('Pro smazání týmu musíš potvrdit přesný název týmu.', 'error')
                log_event('team.delete_failed', team_id=team.id, role='coach', level='warning', message='Delete confirmation did not match team name')
                return redirect(url_for('settings'))
            # delete related rows
            from coach.models import Player, Roster, LineAssignment, Drill, TrainingSession, LineupSession, TrainingEvent, TeamKey, AuditEvent, AttendanceEntry, LeagueIntegration, TeamLoginAttempt
            try:
                # remove export files
                from flask import current_app
                import os
                export_dir = current_app.config['EXPORT_FOLDER']
                for sess in TrainingSession.query.filter_by(team_id=team.id).all():
                    fpath = os.path.join(export_dir, sess.filename)
                    try:
                        if os.path.isfile(fpath):
                            os.remove(fpath)
                    except Exception:
                        pass
                for sess in LineupSession.query.filter_by(team_id=team.id).all():
                    fpath = os.path.join(export_dir, sess.filename)
                    try:
                        if os.path.isfile(fpath):
                            os.remove(fpath)
                    except Exception:
                        pass
                # delete rows
                for mdl in (Roster, LineAssignment, AttendanceEntry, Player, Drill, TrainingSession, LineupSession, TrainingEvent, LeagueIntegration, TeamLoginAttempt, TeamKey, AuditEvent):
                    mdl.query.filter_by(team_id=team.id).delete()
                db.session.delete(team)
                db.session.commit()
                flash('Tým byl smazán.', 'info')
            except Exception:
                db.session.rollback()
                flash('Nepodařilo se smazat tým.', 'error')
            # logout team session
            from flask import session
            session.pop('team_id', None)
            session.pop('team_role', None)
            session.pop('team_login', None)
            return redirect(url_for('team_auth'))
    members = []
    from coach.services.league import service as league_svc
    from coach.services import tymuj as tymuj_svc
    league = league_svc.get_view(tid)
    league_cfg = league_svc.get_integration(tid)
    tymuj_status = tymuj_svc.get_status(tid) if tid else {}
    return render_template('settings.html', team=team, members=members, league=league, league_cfg=league_cfg, tymuj_status=tymuj_status)


@bp.route('/team/members/action', methods=['POST'], endpoint='team_members_action')
@team_login_required
def team_members_action():
    # Members management removed in team-only mode
    return redirect(url_for('settings'))
