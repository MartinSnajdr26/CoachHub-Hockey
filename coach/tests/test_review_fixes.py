import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from coach.app import app
from coach.extensions import db
from coach.models import (
    AttendanceEntry,
    LeagueIntegration,
    LineAssignment,
    Player,
    Roster,
    Team,
    TeamLoginAttempt,
    TrainingEvent,
)


class ReviewFixesTest(unittest.TestCase):
    def setUp(self):
        app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        )
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.team = Team(name='Alpha')
        self.other = Team(name='Beta')
        db.session.add_all([self.team, self.other])
        db.session.commit()
        self.player = Player(team_id=self.team.id, name='A Player', position='F')
        self.other_player = Player(team_id=self.other.id, name='B Player', position='D')
        db.session.add_all([self.player, self.other_player])
        db.session.commit()
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess['team_id'] = self.team.id
            sess['team_role'] = 'coach'
            sess['team_login'] = True

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_roster_rejects_other_team_and_bad_ids(self):
        res = self.client.post('/roster', data={'players': [str(self.player.id), str(self.other_player.id), 'bad']})
        self.assertEqual(res.status_code, 302)
        rows = Roster.query.filter_by(team_id=self.team.id).all()
        self.assertEqual([r.player_id for r in rows], [self.player.id])

    def test_delete_player_removes_dependent_rows(self):
        event = TrainingEvent(team_id=self.team.id, day=date(2026, 6, 28), title='Training')
        db.session.add(event)
        db.session.add(Roster(team_id=self.team.id, player_id=self.player.id))
        db.session.add(LineAssignment(team_id=self.team.id, player_id=self.player.id, slot='L1LW'))
        db.session.add(AttendanceEntry(
            team_id=self.team.id,
            player_id=self.player.id,
            event_key='local:1',
            event_title='Training',
            event_day=date(2026, 6, 28),
            status='going',
        ))
        db.session.commit()

        res = self.client.post(f'/delete_player/{self.player.id}')
        self.assertEqual(res.status_code, 302)
        self.assertIsNone(Player.query.get(self.player.id))
        self.assertEqual(Roster.query.filter_by(player_id=self.player.id).count(), 0)
        self.assertEqual(LineAssignment.query.filter_by(player_id=self.player.id).count(), 0)
        self.assertEqual(AttendanceEntry.query.filter_by(player_id=self.player.id).count(), 0)

    def test_team_delete_requires_exact_server_side_confirmation(self):
        db.session.add(LeagueIntegration(team_id=self.team.id, enabled=True, source_url='https://example.com'))
        db.session.add(TeamLoginAttempt(team_id=self.team.id, ip_truncated='127.0.0.0', attempts=1))
        db.session.commit()

        res = self.client.post('/settings', data={'action': 'delete_team', 'confirm_team_name': 'Wrong'})
        self.assertEqual(res.status_code, 302)
        self.assertIsNotNone(Team.query.get(self.team.id))

        res = self.client.post('/settings', data={'action': 'delete_team', 'confirm_team_name': 'Alpha'})
        self.assertEqual(res.status_code, 302)
        self.assertIsNone(Team.query.get(self.team.id))
        self.assertEqual(LeagueIntegration.query.filter_by(team_id=self.team.id).count(), 0)
        self.assertEqual(TeamLoginAttempt.query.filter_by(team_id=self.team.id).count(), 0)


if __name__ == '__main__':
    unittest.main()
