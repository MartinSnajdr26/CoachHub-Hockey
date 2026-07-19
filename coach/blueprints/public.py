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
    # Browsers accept PNG via rel=icon; this must never be a per-team logo.
    try:
        return send_from_directory(current_app.static_folder, 'icon-192.png')
    except Exception:
        return ('', 404)
