from flask import (Blueprint, redirect, render_template, current_app,
                   send_from_directory, url_for)

from coach.extensions import limiter

bp = Blueprint('public', __name__)


@bp.route('/', endpoint='welcome')
def welcome():
    """Landing page — unless this browser has an onboarding claim to finish.

    "Open CoachHub again and carry on" is the whole point of the resume cookie:
    a player who was waiting for approval lands straight back on their claim
    instead of being asked for the shared player key a second time. Only a live
    (pending/approved, unexpired) claim redirects; a dead cookie falls through
    to the normal landing page and is cleaned up by the onboarding view.
    """
    from coach.services import onboarding_resume as resume
    try:
        if resume.has_resumable_claim():
            return redirect(url_for('playerauth.onboarding'))
    except Exception:      # never let the landing page fail on a DB hiccup
        current_app.logger.warning('resume check failed on /', exc_info=True)
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
