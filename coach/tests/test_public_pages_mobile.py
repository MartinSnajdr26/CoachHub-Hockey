# -*- coding: utf-8 -*-
"""Public / auth / legal / error pages batch. Most pages are already responsive
via dedicated CSS; this suite verifies they render safely, expose no private
data, and that Team Create Result gained a mobile copy hook without leaking keys.
"""
import unittest

from coach.app import app
from coach.extensions import db
from coach.models import Team, TeamKey
from coach.services.keys import hash_team_key


class PublicPagesTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    # ---- public/legal/error pages render (no auth) ----
    def test_public_pages_render(self):
        for path in ('/', '/team/auth', '/terms', '/privacy', '/about'):
            r = self.client.get(path)
            self.assertIn(r.status_code, (200,), '%s -> %s' % (path, r.status_code))

    def test_team_auth_has_csrf_and_login_form(self):
        h = self.client.get('/team/auth').get_data(as_text=True)
        self.assertIn('csrf_token', h)
        self.assertIn('/team/login', h)        # login POST action present
        self.assertIn('name="key"', h)

    def test_public_pages_no_authenticated_bottom_nav(self):
        # Not logged in: the authenticated bottom nav (mnav) must not render.
        for path in ('/', '/team/auth', '/terms', '/privacy', '/about'):
            h = self.client.get(path).get_data(as_text=True)
            self.assertNotIn('class="mnav"', h, path)

    # ---- terms consent (requires a team session; the approval gate excludes it) ----
    def test_terms_consent_renders_form_with_csrf(self):
        team = Team(name='HC Consent'); db.session.add(team); db.session.flush()
        with self.client.session_transaction() as s:
            s['team_id'] = team.id; s['team_role'] = 'coach'; s['team_login'] = True
        r = self.client.get('/terms/consent')
        self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        self.assertIn('csrf_token', h)
        self.assertIn('Souhlasím', h)          # accept action present
        self.assertIn('/terms/consent', h)     # posts to same route

    # ---- error 500 ----
    def test_500_template_is_safe_and_has_recovery(self):
        from flask import render_template
        with app.test_request_context('/'):
            html = render_template('500.html')
        self.assertIn('Aplikace narazila na chybu', html)
        self.assertIn('/app', html)            # base header brand links to home
        self.assertIn('CoachHub', html)
        for leak in ('Traceback', 'Exception', '/home/', 'SECRET', 'sqlite'):
            self.assertNotIn(leak, html)

    # ---- team creation result: keys shown, copy hook added, keys not in URL ----
    def test_team_create_result_keys_copy_hook_no_url_leak(self):
        r = self.client.post('/team/create', data={'team_name': 'HC Test Mobile', 'terms_accept': 'on'})
        self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        self.assertIn('zobrazí se jen jednou', h)     # shown-once warning
        self.assertIn('tcrm-copy', h)                 # mobile copy hook (partial included)
        import re
        keys = re.findall(r'<code>([^<]+)</code>', h)
        self.assertEqual(len(keys), 2)                # coach + player
        for key in keys:
            self.assertNotIn('href="%s' % key, h)             # never in a link
            self.assertNotIn('?text=%s' % key, h)             # not in a share URL
            self.assertNotIn(key, r.headers.get('Location', ''))  # not in a redirect URL
            # each key appears only inside its <code> block, not elsewhere in the page
            self.assertEqual(h.count(key), 1)

    def test_team_create_result_new_team_persisted_once(self):
        before = Team.query.count()
        self.client.post('/team/create', data={'team_name': 'HC Once', 'terms_accept': 'on'})
        self.assertEqual(Team.query.count(), before + 1)
        # two keys stored (coach + player), hashed (not plaintext in DB is a model concern)
        t = Team.query.filter_by(name='HC Once').first()
        self.assertIsNotNone(t)
        self.assertEqual(TeamKey.query.filter_by(team_id=t.id).count(), 2)


if __name__ == '__main__':
    unittest.main()
