# -*- coding: utf-8 -*-
"""Formace 2.0: render, modes, substitutes, special teams, save/load, export."""
import unittest

from coach.app import app
from coach.extensions import db
from coach.models import LineAssignment, Player, Roster, Team, TeamKey
from coach.services.keys import hash_team_key


class LinesTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='HC Test'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('ck')))
        self.f = Player(team_id=self.tid, name='Forward One', position='F')
        self.d = Player(team_id=self.tid, name='Defense One', position='D')
        self.g = Player(team_id=self.tid, name='Goalie One', position='G')
        db.session.add_all([self.f, self.d, self.g]); db.session.flush()
        for p in (self.f, self.d, self.g):
            db.session.add(Roster(team_id=self.tid, player_id=p.id))
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self, role='coach'):
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid; s['team_role'] = role; s['team_login'] = True

    def test_page_renders_with_modes_subs_special_teams(self):
        self._login('coach')
        r = self.client.get('/lines')
        self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        self.assertIn('data-mode-btn="5v5"', h)
        self.assertIn('data-mode-btn="st"', h)
        self.assertIn('data-mode="st"', h)            # special teams section
        self.assertIn('subs-card', h)                 # substitutes
        self.assertIn('data-slot="SUBF1"', h)
        self.assertIn('data-slot="PP1_1"', h)         # power play
        self.assertIn('data-slot="PK1A1"', h)         # penalty kill
        self.assertIn('data-slot="TVG"', h)           # 3v3 goalie
        self.assertIn('id="lineup-validation"', h)    # validation panel
        self.assertIn('rink-surface', h)              # rink background

    def test_pool_contains_players(self):
        self._login('coach')
        h = self.client.get('/lines').get_data(as_text=True)
        self.assertIn('Forward One', h)
        self.assertIn('Defense One', h)
        self.assertIn('Goalie One', h)

    def test_save_5v5_and_subs_and_special_teams(self):
        self._login('coach')
        r = self.client.post('/lines', data={
            'L1LW': self.f.id, 'D1LD': self.d.id, 'G1': self.g.id,
            'SUBF1': self.f.id,                 # forward also a sub (different group ok at storage)
            'PP1_1': self.f.id, 'PP1_2': self.d.id,  # power play overlaps line (allowed)
            'TVG': self.g.id,
        })
        self.assertEqual(r.status_code, 302)
        slots = {a.slot: a.player_id for a in LineAssignment.query.filter_by(team_id=self.tid).all()}
        self.assertEqual(slots.get('L1LW'), self.f.id)
        self.assertEqual(slots.get('G1'), self.g.id)
        self.assertEqual(slots.get('SUBF1'), self.f.id)
        self.assertEqual(slots.get('PP1_1'), self.f.id)
        self.assertEqual(slots.get('PP1_2'), self.d.id)
        self.assertEqual(slots.get('TVG'), self.g.id)

    def test_saved_assignment_renders_back(self):
        self._login('coach')
        db.session.add(LineAssignment(team_id=self.tid, player_id=self.f.id, slot='PP1_1'))
        db.session.commit()
        h = self.client.get('/lines').get_data(as_text=True)
        # the PP1_1 slot hidden input now carries the player id
        self.assertIn('name="PP1_1" value="%d"' % self.f.id, h)

    def test_save_rejects_non_roster_player(self):
        self._login('coach')
        other = Team(name='Other'); db.session.add(other); db.session.flush()
        op = Player(team_id=other.id, name='X', position='F'); db.session.add(op); db.session.commit()
        self.client.post('/lines', data={'L1LW': op.id})
        self.assertEqual(LineAssignment.query.filter_by(team_id=self.tid).count(), 0)

    def test_player_cannot_save(self):
        self._login('player')
        r = self.client.post('/lines', data={'L1LW': self.f.id})
        self.assertEqual(r.status_code, 302)             # coach_required redirect
        self.assertEqual(LineAssignment.query.filter_by(team_id=self.tid).count(), 0)

    def test_export_pdf_with_special_teams(self):
        self._login('coach')
        for slot, pid in [('L1LW', self.f.id), ('SUBF1', self.f.id), ('PP1_1', self.f.id), ('TVG', self.g.id)]:
            db.session.add(LineAssignment(team_id=self.tid, player_id=pid, slot=slot))
        db.session.commit()
        r = self.client.post('/lines/export_pdf', data={'opponent': 'Rival', 'date': '2026-09-01'})
        self.assertEqual(r.status_code, 302)             # redirect to export result


if __name__ == '__main__':
    unittest.main()
