import os
import sys
import unittest
from datetime import date
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from coach.app import app
from coach.extensions import db
from coach.models import AuditEvent, Drill, Player, Roster, Team, TeamKey, TrainingEvent
from coach.services import tymuj as tymuj_svc
from coach.services.league import service as league_svc
from coach.services.keys import hash_team_key


ICS_SAMPLE = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART:20260629T180000Z
SUMMARY:Trenink
ATTENDEE;CN=Jan Novak:mailto:jan@example.com
ATTENDEE;CN=Petr Svoboda:mailto:petr@example.com
END:VEVENT
END:VCALENDAR
"""


class StabilizationTest(unittest.TestCase):
    def setUp(self):
        app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            ADMIN_SECRET_KEY='owner-secret',
        )
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.team = Team(name='Stabilized', tymuj_ics_url='https://example.com/team.ics')
        db.session.add(self.team)
        db.session.flush()
        self.team_id = self.team.id
        self.tymuj_ics_url = self.team.tymuj_ics_url
        db.session.add(TeamKey(team_id=self.team_id, role='coach', key_hash=hash_team_key('coach-key')))
        db.session.add(TeamKey(team_id=self.team_id, role='player', key_hash=hash_team_key('player-key')))
        player = Player(team_id=self.team_id, name='Jan Novak', position='F')
        db.session.add(player)
        db.session.flush()
        db.session.add(Roster(team_id=self.team_id, player_id=player.id))
        db.session.add(TrainingEvent(team_id=self.team_id, day=date(2026, 6, 28), time='18:00', title='Local Training'))
        db.session.add(Drill(team_id=self.team_id, name='Skate', category='Skating', path_data='[]'))
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def login(self, role='coach'):
        with self.client.session_transaction() as sess:
            sess['team_id'] = self.team_id
            sess['team_role'] = role
            sess['team_login'] = True

    def test_tymuj_parser_and_cache(self):
        events = tymuj_svc.parse_events(ICS_SAMPLE)
        names = tymuj_svc.parse_participants(ICS_SAMPLE)
        self.assertEqual(events[0]['day'], '2026-06-29')
        self.assertEqual(events[0]['time'], '18:00')
        self.assertEqual(names, ['Jan Novak', 'Petr Svoboda'])

        AuditEvent.query.delete()
        db.session.add(AuditEvent(
            event=tymuj_svc.CACHE_EVENT,
            team_id=self.team_id,
            meta='{"events":[{"day":"2026-06-29","time":"18:00","title":"Trenink","kind":"tymuj","source":"tymuj"}],"participants":["Jan Novak"]}',
        ))
        db.session.commit()
        cached = tymuj_svc.get_cached_events(self.team_id, date(2026, 6, 1), date(2026, 6, 30))
        self.assertEqual(len(cached), 1)
        self.assertEqual(tymuj_svc.get_cached_participants(self.team_id), ['Jan Novak'])

    def test_dashboard_and_attendance_do_not_fetch_tymuj_on_render(self):
        self.login('coach')
        with patch('coach.services.tymuj.safe_urlopen') as urlopen:
            self.assertEqual(self.client.get('/app?year=2026&month=6').status_code, 200)
            self.assertEqual(self.client.get('/dochazka').status_code, 200)
            self.assertEqual(self.client.get('/players/import/tymuj').status_code, 200)
            self.assertFalse(urlopen.called)

    def test_main_routes_render_for_coach(self):
        self.login('coach')
        for route in ('/app', '/dochazka', '/players', '/roster', '/lines', '/drills', '/drills/Skating', '/drills/select', '/settings'):
            with self.subTest(route=route):
                self.assertEqual(self.client.get(route).status_code, 200)

    def test_auth_login_and_permissions(self):
        res = self.client.post('/team/login', data={
            'team_id': self.team_id,
            'role': 'coach',
            'key': 'coach-key',
            'terms_accept': 'on',
        })
        self.assertEqual(res.status_code, 302)
        self.assertIn('/app', res.headers['Location'])

        self.login('player')
        denied = self.client.get('/settings')
        self.assertEqual(denied.status_code, 302)

    def test_owner_routes_require_owner_access(self):
        self.login('coach')
        res = self.client.get('/owner')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/owner/login', res.headers['Location'])
        self.assertEqual(self.client.get('/owner/login').status_code, 200)
        self.assertEqual(self.client.get('/owner/league-debug').status_code, 302)

        res = self.client.post('/owner/login', data={'owner_key': 'owner-secret'})
        self.assertEqual(res.status_code, 302)
        self.assertIn('/owner', res.headers['Location'])
        self.assertEqual(self.client.get('/owner').status_code, 200)
        self.assertEqual(self.client.get('/owner/dashboard').status_code, 302)
        self.assertEqual(self.client.get('/owner/integrations').status_code, 200)
        self.assertEqual(self.client.get('/owner/health').status_code, 200)
        self.assertEqual(self.client.get('/owner/league-debug').status_code, 200)

    def test_integration_failures_are_logged_and_dashboard_survives(self):
        self.login('coach')
        league_svc.save_config(self.team_id, True, 'https://example.com/league', 'Stabilized')
        with patch('coach.services.league.base.fetch_html', side_effect=TimeoutError('league timeout')):
            ok, _msg = league_svc.refresh(self.team_id, manual=True)
        self.assertFalse(ok)
        self.assertIsNotNone(AuditEvent.query.filter_by(event='integration.league.failure', team_id=self.team_id).first())

        with patch('coach.services.tymuj.safe_urlopen', side_effect=TimeoutError('tymuj timeout')):
            ok, msg = tymuj_svc.refresh_cache(self.team_id, self.tymuj_ics_url)
        self.assertFalse(ok)
        self.assertEqual(msg, 'Týmuj data could not be refreshed. Showing last saved data.')
        self.assertIsNotNone(AuditEvent.query.filter_by(event='integration.tymuj.failure', team_id=self.team_id).first())
        self.assertEqual(self.client.get('/app').status_code, 200)


if __name__ == '__main__':
    unittest.main()
