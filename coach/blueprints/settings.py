from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
from coach.auth_utils import team_login_required, get_team_id, coach_required
from coach.extensions import db
from coach.models import Team, AuditEvent

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
            if logo_f and getattr(logo_f, 'filename', ''):
                err, rel = _save_logo_file(logo_f)
                if err:
                    flash(err, 'error')
                    return redirect(url_for('settings'))
                if rel:
                    team.logo_path = rel
            db.session.commit()
            try:
                db.session.add(AuditEvent(event='team.brand_update', team_id=team.id, role='coach', ip_truncated=request.remote_addr or '-', meta='{}'))
                db.session.commit()
            except Exception:
                pass
            return redirect(url_for('settings'))
        elif action == 'delete_team':
            # coach-only
            resp = coach_required(lambda: None)()
            if resp is not None:
                return resp
            if not team:
                return redirect(url_for('team_auth'))
            # delete related rows
            from coach.models import Player, Roster, LineAssignment, Drill, TrainingSession, LineupSession, TrainingEvent, TeamKey, AuditEvent
            try:
                # remove export files
                from flask import current_app
                export_dir = current_app.config['EXPORT_FOLDER']
                for sess in TrainingSession.query.filter_by(team_id=team.id).all():
                    import os
                    fpath = os.path.join(export_dir, sess.filename)
                    try:
                        if os.path.isfile(fpath):
                            os.remove(fpath)
                    except Exception:
                        pass
                # delete rows
                for mdl in (Roster, LineAssignment, Player, Drill, TrainingSession, LineupSession, TrainingEvent, TeamKey, AuditEvent):
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
    return render_template('settings.html', team=team, members=members)


@bp.route('/team/members/action', methods=['POST'], endpoint='team_members_action')
@team_login_required
def team_members_action():
    # Members management removed in team-only mode
    return redirect(url_for('settings'))
