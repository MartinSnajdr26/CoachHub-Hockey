import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from coach.app import app
from coach.extensions import db
from coach.models import Team
from coach.services.league import service as league_svc
from coach.tests.test_league_pipeline_hotfix import HOCKEY_LAYOUT, URL


class OwnerLeagueDebugTest(unittest.TestCase):
    def setUp(self):
        app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            ADMIN_SECRET_KEY='owner-secret',
            IS_DEV=False,
        )
        self.ctx = app.app_context()
        self.ctx.push()
        try:
            db.drop_all()
        except Exception:
            db.session.rollback()
        db.create_all()
        team = Team(name='HC Smíchov 1913')
        db.session.add(team)
        db.session.flush()
        self.team_id = team.id
        db.session.commit()
        league_svc.save_config(self.team_id, True, URL, 'HC Smíchov 1913')
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove()
        try:
            db.drop_all()
        except Exception:
            db.session.rollback()
        self.ctx.pop()

    def test_owner_link_hidden_for_normal_team_session_and_visible_for_owner(self):
        with self.client.session_transaction() as sess:
            sess['team_id'] = self.team_id
            sess['team_role'] = 'coach'
            sess['team_login'] = True
        body = self.client.get('/app').get_data(as_text=True)
        self.assertNotIn('>Owner<', body)

        with self.client.session_transaction() as sess:
            sess['owner_admin'] = True
            sess['team_id'] = self.team_id
            sess['team_role'] = 'coach'
            sess['team_login'] = True
        body = self.client.get('/app').get_data(as_text=True)
        self.assertIn('⚙ Owner', body)

    def test_league_debug_requires_owner_and_runs_diagnostic_refresh(self):
        with self.client.session_transaction() as sess:
            sess['team_id'] = self.team_id
            sess['team_role'] = 'coach'
            sess['team_login'] = True
        denied = self.client.get('/owner/league-debug')
        self.assertEqual(denied.status_code, 302)
        self.assertIn('/owner/login', denied.headers['Location'])

        self.client.post('/owner/login', data={'owner_key': 'owner-secret'})
        page = self.client.get('/owner/league-debug')
        self.assertEqual(page.status_code, 200)
        self.assertIn('League Integration Developer Tools', page.get_data(as_text=True))

        with patch('coach.services.league.service.validate_public_http_url', return_value=(True, '')), \
             patch('coach.services.league.service.fetch_html_with_meta',
                   return_value=(HOCKEY_LAYOUT, {'http_status': 200, 'bytes': len(HOCKEY_LAYOUT), 'encoding': 'utf-8'})):
            res = self.client.post('/owner/league-debug', data={'team_id': self.team_id})
        self.assertEqual(res.status_code, 200)
        body = res.get_data(as_text=True)
        self.assertIn('Diagnostic Refresh Trace', body)
        self.assertIn('dashboard view model result', body)

        view = league_svc.get_view(self.team_id)
        self.assertFalse(view['stale_schema'])
        self.assertEqual(view['team_row']['team_name'], 'HC Smíchov 1913')
        self.assertEqual(view['team_row']['points'], 22)
        self.assertTrue(view['results'])
        self.assertTrue(view['form_cards'])


if __name__ == '__main__':
    unittest.main()
