# -*- coding: utf-8 -*-
"""Saved sessions & export selection batch — mobile layers for Drill Select,
Saved Training Sessions, Session Detail, and Saved Lineups. Verifies each mobile
layer renders, forms/fields are reused, team isolation + permissions hold, and
desktop markup remains.
"""
import unittest

from coach.app import app
from coach.extensions import db
from coach.models import Drill, LineupSession, Team, TeamKey, TrainingSession
from coach.services.keys import hash_team_key


class _Fixture(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='HC Smíchov'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('ck')))
        self.other = Team(name='HC Soupeř'); db.session.add(self.other); db.session.flush()
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self, role='coach', tid=None):
        with self.client.session_transaction() as s:
            s['team_id'] = tid or self.tid; s['team_role'] = role; s['team_login'] = True


class DrillSelectMobileTest(_Fixture):
    def setUp(self):
        super().setUp()
        db.session.add(Drill(team_id=self.tid, name='Naše cvičení', category='Útok'))
        db.session.add(Drill(team_id=self.other.id, name='Cizí cvičení', category='Útok'))
        db.session.commit()

    def test_renders_mobile_layer_team_scoped_form(self):
        self._login('coach')
        h = self.client.get('/drills/select').get_data(as_text=True)
        self.assertIn('dsm-bar', h)
        self.assertIn('id="exportForm"', h)             # desktop selection form
        self.assertIn('name="drill_ids"', h)            # selection field preserved
        self.assertIn('Naše cvičení', h)
        self.assertNotIn('Cizí cvičení', h)             # other team excluded
        self.assertIn('csrf_token', h)

    def test_player_renders_without_functional_export(self):
        self._login('player')
        r = self.client.get('/drills/select')
        self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        self.assertIn('dsm-bar', h)
        self.assertIn('Pouze trenér může exportovat', h)  # coach-only submit disabled


class DrillSessionsMobileTest(_Fixture):
    def setUp(self):
        super().setUp()
        db.session.add(TrainingSession(team_id=self.tid, title='Náš trénink', filename='-', drill_ids=''))
        db.session.add(TrainingSession(team_id=self.other.id, title='Cizí trénink', filename='-', drill_ids=''))
        db.session.commit()

    def test_renders_mobile_layer_team_scoped(self):
        self._login('coach')
        h = self.client.get('/drill-sessions').get_data(as_text=True)
        self.assertIn('tsm-bar', h)
        self.assertIn('Náš trénink', h)
        self.assertNotIn('Cizí trénink', h)
        self.assertIn('class="cards"', h)                # desktop list remains
        self.assertIn('/drill-sessions/', h)             # open-detail link preserved

    def test_player_no_delete(self):
        self._login('player')
        h = self.client.get('/drill-sessions').get_data(as_text=True)
        self.assertIn('tsm-bar', h)
        self.assertNotIn('delete_drill_session', h.replace('/', '_'))  # coach-only delete form absent


class SessionDetailMobileTest(_Fixture):
    def setUp(self):
        super().setUp()
        self.d1 = Drill(team_id=self.tid, name='Drill AAA', category='Útok', duration=5)
        self.d2 = Drill(team_id=self.tid, name='Drill BBB', category='Obrana', duration=7)
        db.session.add_all([self.d1, self.d2]); db.session.flush()
        # saved order: d2 then d1
        self.sess = TrainingSession(team_id=self.tid, title='Trénink X', filename='-',
                                    drill_ids='%d,%d' % (self.d2.id, self.d1.id))
        self.other_sess = TrainingSession(team_id=self.other.id, title='Cizí', filename='-', drill_ids='')
        db.session.add_all([self.sess, self.other_sess]); db.session.commit()

    def test_renders_mobile_layer_order_preserved(self):
        self._login('coach')
        h = self.client.get('/drill-sessions/%d' % self.sess.id).get_data(as_text=True)
        self.assertIn('tsdm-bar', h)
        self.assertIn('Drill AAA', h)
        self.assertIn('Drill BBB', h)
        self.assertLess(h.index('Drill BBB'), h.index('Drill AAA'))  # saved order (d2 first)
        self.assertIn('/drill/%d' % self.d1.id, h)       # drill-detail link preserved
        self.assertIn('btn-quick-play', h)               # quick-play reused

    def test_other_team_detail_blocked(self):
        self._login('coach')
        self.assertEqual(self.client.get('/drill-sessions/%d' % self.other_sess.id).status_code, 302)


class LineupSessionsMobileTest(_Fixture):
    def setUp(self):
        super().setUp()
        db.session.add(LineupSession(team_id=self.tid, title='Naše sestava', filename='lineup-x.pdf'))
        db.session.add(LineupSession(team_id=self.other.id, title='Cizí sestava', filename='lineup-y.pdf'))
        db.session.commit()

    def test_renders_mobile_layer_team_scoped(self):
        self._login('coach')
        h = self.client.get('/lineup-sessions').get_data(as_text=True)
        self.assertIn('lsm-bar', h)
        self.assertIn('Naše sestava', h)
        self.assertNotIn('Cizí sestava', h)
        self.assertIn('class="cards"', h)                # desktop list remains
        self.assertIn('/exports/lineup-x.pdf', h)        # download via protected route

    def test_player_no_delete(self):
        self._login('player')
        h = self.client.get('/lineup-sessions').get_data(as_text=True)
        self.assertIn('lsm-bar', h)
        self.assertNotIn('delete_lineup_session', h.replace('/', '_'))


if __name__ == '__main__':
    unittest.main()
