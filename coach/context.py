from flask import url_for
from flask_login import current_user
from flask import session
from coach.models import Team, Drill

def register_context(app):
    @app.context_processor
    def inject_brand():
        brand = {'logo_url': None, 'primary': None, 'secondary': None, 'team_name': None}
        try:
            team_id = session.get('team_id') or (current_user.team_id if current_user.is_authenticated else None)
            if team_id:
                t = Team.query.get(team_id)
                if t:
                    if t.logo_path:
                        brand['logo_url'] = url_for('static', filename=t.logo_path)
                    brand['primary'] = t.primary_color or None
                    brand['secondary'] = t.secondary_color or None
                    brand['team_name'] = t.name or None
        except Exception as e:
            try:
                app.logger.warning('inject_brand failed: %s', e)
            except Exception:
                pass
        return dict(brand=brand)

    @app.context_processor
    def inject_drill_nav():
        from coach.extensions import db
        try:
            q = db.session.query(Drill.category)
            team_id = session.get('team_id') or (current_user.team_id if current_user.is_authenticated else None)
            if team_id:
                q = q.filter(Drill.team_id == team_id)
            cats = q.distinct().all()
            categories = [c[0] for c in cats if c and c[0]]
        except Exception:
            categories = []
        # role shortcuts for templates
        role = session.get('team_role') or (getattr(current_user, 'role', 'player') if current_user.is_authenticated else 'player')
        return {'nav_drill_categories': categories, 'team_session_login': bool(session.get('team_login')), 'team_session_role': role, 'is_coach': role == 'coach' or (current_user.is_authenticated and getattr(current_user, 'role', 'player') == 'coach')}
