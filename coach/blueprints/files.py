from flask import Blueprint, redirect, url_for, flash, current_app, send_file
from flask_login import current_user
from coach.auth_utils import team_login_required, get_team_id
import os
from coach.models import TrainingSession, LineupSession

bp = Blueprint('files', __name__)


@bp.route('/exports/<path:filename>', endpoint='download_export')
@team_login_required
def download_export(filename):
    allowed = False
    tid = get_team_id()
    if tid is not None:
        ts = TrainingSession.query.filter_by(team_id=tid, filename=filename).first()
        ls = LineupSession.query.filter_by(team_id=tid, filename=filename).first()
        allowed = bool(ts or ls)
    else:
        ts = TrainingSession.query.filter_by(team_id=None, filename=filename).first()
        ls = LineupSession.query.filter_by(team_id=None, filename=filename).first()
        allowed = bool(ts or ls)
    if not allowed:
        flash('Soubor nepatří do vašeho týmu.', 'error')
        return redirect(url_for('home'))
    base = os.path.abspath(current_app.config['EXPORT_FOLDER'])
    fpath = os.path.abspath(os.path.join(base, filename))
    if not fpath.startswith(base + os.sep):
        flash('Neplatný název souboru.', 'error')
        return redirect(url_for('home'))
    try:
        return send_file(fpath, mimetype='application/pdf', as_attachment=False)
    except Exception:
        flash('Soubor nebyl nalezen.', 'error')
        return redirect(url_for('home'))
