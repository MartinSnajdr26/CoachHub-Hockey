# -*- coding: utf-8 -*-
"""Mobile Practice Detail: the additive mobile partial renders alongside the
untouched desktop viewer, reuses the single #board canvas, respects permissions
and tenant isolation, and is excluded from embed mode.
"""
import unittest

from coach.app import app
from coach.extensions import db
from coach.models import Drill, Team, TeamKey
from coach.services.keys import hash_team_key


class DrillDetailMobileTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='HC Smíchov'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('ck')))
        self.drill = Drill(team_id=self.tid, name='Bruslení vpřed', category='Rozbruslení',
                           description='Začni u modré.\nDvě řady.', duration=12, path_data='[]')
        db.session.add(self.drill)
        self.other = Team(name='HC Soupeř'); db.session.add(self.other); db.session.flush()
        self.other_drill = Drill(team_id=self.other.id, name='Cizí cvičení', category='Obrana', path_data='[]')
        db.session.add(self.other_drill)
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self, role='coach'):
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid; s['team_role'] = role; s['team_login'] = True

    # ---- renders + reuses the single canvas ----
    def test_renders_mobile_layer_and_single_canvas(self):
        self._login('coach')
        r = self.client.get('/drill/%d' % self.drill.id)
        self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        self.assertIn('ddm-bar', h)              # mobile app bar
        self.assertIn('Detail cvičení', h)
        self.assertIn('ddm-ctrl', h)             # mobile playback controls
        # The canvas is reused, not duplicated.
        self.assertEqual(h.count('id="board"'), 1)

    # ---- description present and collapsible ----
    def test_description_section_present(self):
        self._login('coach')
        h = self.client.get('/drill/%d' % self.drill.id).get_data(as_text=True)
        self.assertIn('Popis cvičení', h)
        self.assertIn('ddm-desc-body', h)

    # ---- permissions ----
    def test_coach_sees_overflow_and_delete(self):
        self._login('coach')
        h = self.client.get('/drill/%d' % self.drill.id).get_data(as_text=True)
        self.assertIn('ddm-ov-btn', h)
        self.assertIn('Smazat cvičení', h)

    def test_player_can_view_but_no_coach_controls(self):
        self._login('player')
        r = self.client.get('/drill/%d' % self.drill.id)
        self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        self.assertIn('ddm-bar', h)              # player can view + play
        self.assertIn('ddm-ctrl', h)
        self.assertNotIn('ddm-ov-btn', h)        # no overflow menu
        self.assertNotIn('Smazat cvičení', h)    # no delete

    # ---- tenant isolation ----
    def test_other_team_drill_blocked(self):
        self._login('coach')
        r = self.client.get('/drill/%d' % self.other_drill.id)
        self.assertEqual(r.status_code, 302)

    # ---- embed mode excludes the mobile layer ----
    def test_embed_mode_excludes_mobile_partial(self):
        self._login('coach')
        h = self.client.get('/drill/%d?embed=1' % self.drill.id).get_data(as_text=True)
        self.assertNotIn('ddm-bar', h)
        self.assertEqual(h.count('id="board"'), 1)


if __name__ == '__main__':
    unittest.main()
