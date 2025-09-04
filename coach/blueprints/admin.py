from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import current_user
from coach.auth_utils import team_login_required, get_team_id, coach_required
from coach.models import AuditEvent

bp = Blueprint('admin', __name__)


@bp.route('/admin/audit-log', endpoint='audit_log')
@team_login_required
def audit_log():
    # coach-only (team session)
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    tid = get_team_id()
    logs = []
    if tid:
        logs = (AuditEvent.query
                .filter_by(team_id=tid)
                .order_by(AuditEvent.created_at.desc())
                .limit(200)
                .all())
    return render_template('audit_log.html', logs=logs, users_by_id={})
