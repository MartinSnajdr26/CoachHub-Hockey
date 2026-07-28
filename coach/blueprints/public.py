from flask import Blueprint, render_template, current_app, send_from_directory

from coach.extensions import limiter

bp = Blueprint('public', __name__)


@bp.route('/', endpoint='welcome')
def welcome():
    return render_template('welcome.html')


@bp.route('/favicon.ico')
@limiter.exempt   # browsers auto-request the favicon; not an abuse vector
def favicon():
    # Serve the CoachHub Hockey app icon (NOT any team/club logo) as the favicon.
    # This is a real multi-size .ico (16/32/48) so legacy /favicon.ico requests get a
    # proper icon; must never be a per-team logo.
    try:
        return send_from_directory(
            current_app.static_folder, 'favicon.ico', mimetype='image/x-icon')
    except Exception:
        return ('', 404)
