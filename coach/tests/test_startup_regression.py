import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from coach.app import app
from coach.extensions import db
from coach.models import Team
from coach.services.db_state import create_missing_dev_tables, has_table
from coach.services.owner_admin import ensure_owner_secret, DEV_TEMP_SECRET


class StartupRegressionTest(unittest.TestCase):
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
        db.session.remove()
        db.drop_all()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_login_page_renders_when_team_table_is_missing(self):
        res = self.client.get('/team/auth')
        self.assertEqual(res.status_code, 200)
        self.assertIn('CoachHub', res.get_data(as_text=True))

    def test_context_brand_defaults_when_team_table_is_missing_with_session(self):
        with self.client.session_transaction() as sess:
            sess['team_id'] = 123
            sess['team_role'] = 'coach'
            sess['team_login'] = True
        res = self.client.get('/team/auth')
        self.assertEqual(res.status_code, 200)
        self.assertIn('CoachHub', res.get_data(as_text=True))

    def test_owner_login_renders_when_database_is_uninitialized(self):
        res = self.client.get('/owner/login', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn('Owner Admin', res.get_data(as_text=True))

    def test_development_bootstrap_creates_temporary_owner_secret(self):
        app.config.update(ADMIN_SECRET_KEY='', OWNER_ACCESS_KEY='', IS_DEV=True)
        app.extensions.pop('coachhub_owner_admin', None)
        with patch('builtins.print') as mock_print:
            secret = ensure_owner_secret(app)
        self.assertEqual(secret, DEV_TEMP_SECRET)
        self.assertEqual(app.config.get('ADMIN_SECRET_KEY'), DEV_TEMP_SECRET)
        self.assertTrue(mock_print.called)

    def test_app_redirect_does_not_crash_when_database_is_uninitialized(self):
        res = self.client.get('/app', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn('CoachHub', res.get_data(as_text=True))

    def test_invalid_session_team_id_is_cleared(self):
        db.create_all()
        with self.client.session_transaction() as sess:
            sess['team_id'] = 'not-an-id'
            sess['team_role'] = 'coach'
            sess['team_login'] = True
        self.assertEqual(self.client.get('/team/auth').status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertNotIn('team_id', sess)
            self.assertNotIn('team_role', sess)
            self.assertNotIn('team_login', sess)

    def test_deleted_team_session_is_cleared(self):
        db.create_all()
        team = Team(name='Deleted Team')
        db.session.add(team)
        db.session.commit()
        team_id = team.id
        db.session.delete(team)
        db.session.commit()
        with self.client.session_transaction() as sess:
            sess['team_id'] = team_id
            sess['team_role'] = 'coach'
            sess['team_login'] = True
        self.assertEqual(self.client.get('/team/auth').status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertNotIn('team_id', sess)
            self.assertNotIn('team_role', sess)
            self.assertNotIn('team_login', sess)

    def test_development_startup_creates_missing_tables(self):
        app.config.update(TESTING=False, IS_DEV=True, AUTO_CREATE_DEV_DB='1')
        create_missing_dev_tables(app)
        self.assertTrue(has_table('team'))


if __name__ == '__main__':
    unittest.main()
