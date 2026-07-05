import os
from datetime import date, datetime, timedelta
from flask import url_for
from flask_login import current_user
from flask import session
from coach.models import Team, Drill, TrainingEvent, AuditEvent, Player, PaymentPeriod, PaymentStatus
from coach.extensions import db
from coach.services.db_state import is_database_not_ready_error, log_db_not_ready_once

# One release/asset version, bumped per deploy (env APP_VERSION overrides). Used
# as the `?v=` cache-buster on frequently-changed application CSS/JS so a new
# release ships a new URL the service worker fetches fresh. Keep in step with the
# service-worker CACHE name in static/sw.js on each release.
ASSET_VERSION = (os.environ.get('APP_VERSION') or 'v4').strip()

def register_context(app):
    @app.context_processor
    def inject_asset_version():
        return {'asset_version': ASSET_VERSION}

    @app.context_processor
    def inject_brand():
        brand = {'logo_url': None, 'primary': None, 'secondary': None, 'tertiary': None, 'team_name': None}
        try:
            team_id = session.get('team_id') or (current_user.team_id if current_user.is_authenticated else None)
            if team_id:
                try:
                    team_id = int(team_id)
                except (TypeError, ValueError):
                    session.pop('team_id', None)
                    session.pop('team_role', None)
                    session.pop('team_login', None)
                    return dict(brand=brand)
                t = Team.query.get(team_id)
                if t:
                    if t.logo_path:
                        brand['logo_url'] = url_for('static', filename=t.logo_path)
                    brand['primary'] = t.primary_color or None
                    brand['secondary'] = t.secondary_color or None
                    brand['tertiary'] = getattr(t, 'tertiary_color', None)
                    brand['team_name'] = t.name or None
                elif session.get('team_id'):
                    session.pop('team_id', None)
                    session.pop('team_role', None)
                    session.pop('team_login', None)
        except Exception as e:
            db.session.rollback()
            if is_database_not_ready_error(e):
                log_db_not_ready_once(app, 'inject-brand-db-not-ready', e, 'inject_brand database is not ready')
            else:
                raise
        return dict(brand=brand)

    @app.context_processor
    def inject_drill_nav():
        try:
            q = db.session.query(Drill.category)
            team_id = session.get('team_id') or (current_user.team_id if current_user.is_authenticated else None)
            if team_id:
                q = q.filter(Drill.team_id == team_id)
            cats = q.distinct().all()
            categories = [c[0] for c in cats if c and c[0]]
        except Exception as e:
            db.session.rollback()
            if is_database_not_ready_error(e):
                log_db_not_ready_once(app, 'inject-drill-nav-db-not-ready', e, 'inject_drill_nav database is not ready')
            else:
                raise
            categories = []
        # role shortcuts for templates
        role = session.get('team_role') or (getattr(current_user, 'role', 'player') if current_user.is_authenticated else 'player')
        return {
            'nav_drill_categories': categories,
            'team_session_login': bool(session.get('team_login')),
            'team_session_role': role,
            'is_coach': role == 'coach' or (current_user.is_authenticated and getattr(current_user, 'role', 'player') == 'coach'),
            'owner_admin_authenticated': bool(session.get('owner_admin')),
        }

    @app.context_processor
    def inject_notifications():
        """Lightweight, read-only notifications for the header bell. A handful of
        cheap queries; safe empty state on any error. No storage, no polling."""
        items = []
        try:
            team_id = session.get('team_id') or (current_user.team_id if current_user.is_authenticated else None)
            if not (team_id and (session.get('team_login') or current_user.is_authenticated)):
                return dict(notifications=[], notifications_count=0)
            team_id = int(team_id)
            role = session.get('team_role') or (getattr(current_user, 'role', 'player') if current_user.is_authenticated else 'player')
            is_coach = (role == 'coach')
            today = date.today()
            tomorrow = today + timedelta(days=1)
            # today's training / game
            ev_today = (TrainingEvent.query.filter_by(team_id=team_id, day=today)
                        .order_by(TrainingEvent.time.asc()).first())
            if ev_today:
                kind = 'Zápas' if (ev_today.kind == 'match') else 'Trénink'
                items.append({'icon': '📅', 'text': 'Dnes %s: %s' % (kind, ev_today.title or ''),
                              'url': url_for('home')})
            # tomorrow's game
            game_tom = (TrainingEvent.query.filter_by(team_id=team_id, day=tomorrow, kind='match')
                        .order_by(TrainingEvent.time.asc()).first())
            if game_tom:
                items.append({'icon': '🥅', 'text': 'Zítra zápas: %s' % (game_tom.title or ''),
                              'url': url_for('home')})
            # new message board post in last 24h
            since = datetime.utcnow() - timedelta(hours=24)
            new_msg = (AuditEvent.query.filter(AuditEvent.team_id == team_id,
                                               AuditEvent.event == 'message',
                                               AuditEvent.created_at >= since).count())
            if new_msg:
                items.append({'icon': '💬', 'text': 'Nové zprávy na nástěnce (%d)' % new_msg,
                              'url': url_for('communication.feed')})
            # unpaid monthly contributions (coach only)
            if is_coach:
                period = PaymentPeriod.query.filter_by(team_id=team_id, year=today.year, month=today.month).first()
                if period:
                    total = Player.query.filter_by(team_id=team_id).count()
                    paid = PaymentStatus.query.filter_by(period_id=period.id, status='paid').count()
                    unpaid = max(0, total - paid)
                    if unpaid:
                        items.append({'icon': '💰', 'text': 'Nezaplacené příspěvky: %d' % unpaid,
                                      'url': url_for('pokladna.pokladna')})
        except Exception as e:
            db.session.rollback()
            if is_database_not_ready_error(e):
                log_db_not_ready_once(app, 'inject-notifications-db-not-ready', e, 'inject_notifications database is not ready')
            return dict(notifications=[], notifications_count=0)
        return dict(notifications=items, notifications_count=len(items))
