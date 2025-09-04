from flask import Blueprint, render_template, request, redirect, url_for, current_app, session
from coach.extensions import db
from coach.models import AuditEvent
from datetime import datetime

bp = Blueprint('legal', __name__)


@bp.route('/terms', endpoint='terms')
def terms():
    return render_template('terms.html', terms_version=current_app.config.get('TERMS_VERSION', 'v1.0'))


@bp.route('/privacy', endpoint='privacy')
def privacy():
    return render_template('privacy.html')

@bp.route('/about', endpoint='about')
def about():
    return render_template('about.html')


@bp.route('/terms/consent', methods=['GET', 'POST'], endpoint='terms_consent')
def terms_consent():
    target = session.pop('after_consent', None)
    if request.method == 'POST':
        # In team-only mode, consent is recorded on team login; nothing to store here.
        return redirect(target or url_for('home'))
    # Store desired next if present
    nxt = request.args.get('next')
    if nxt:
        session['after_consent'] = nxt
    return render_template('terms.html', terms_version=current_app.config.get('TERMS_VERSION', 'v1.0'), consent_mode=True)
