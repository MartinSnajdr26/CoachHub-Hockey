from flask import Blueprint, render_template, current_app, send_from_directory

from coach.extensions import limiter

bp = Blueprint('public', __name__)


@bp.route('/', endpoint='welcome')
def welcome():
    return render_template('welcome.html')


@bp.route('/favicon.ico')
@limiter.exempt   # browsers auto-request the favicon; not an abuse vector
def favicon():
    # Serve a PNG as favicon for simplicity; browsers accept PNG via rel=icon
    try:
        return send_from_directory(current_app.static_folder, 'logo.png')
    except Exception:
        return ('', 404)
