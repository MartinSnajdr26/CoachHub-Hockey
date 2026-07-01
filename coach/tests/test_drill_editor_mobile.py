# -*- coding: utf-8 -*-
"""Mobile drill editor (create + edit share one template/form/route).

Verifies the additive mobile layer renders on both flows without duplicating the
canvas/form, that CSRF is present, and that the existing permission / team-
isolation / create-vs-edit save semantics are unchanged.
"""
import unittest

from coach.app import app
from coach.extensions import db
from coach.models import Drill, Team, TeamKey
from coach.services.keys import hash_team_key


class DrillEditorMobileTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='HC Smíchov'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('ck')))
        self.drill = Drill(team_id=self.tid, name='Bruslení', category='Rozbruslení', duration=10, path_data='[]')
        db.session.add(self.drill)
        self.other = Team(name='HC Soupeř'); db.session.add(self.other); db.session.flush()
        self.other_drill = Drill(team_id=self.other.id, name='Cizí', category='Obrana', path_data='[]')
        db.session.add(self.other_drill)
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self, role='coach'):
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid; s['team_role'] = role; s['team_login'] = True

    # ---- create flow renders, single canvas/form ----
    def test_new_drill_renders_mobile_layer_single_canvas(self):
        self._login('coach')
        h = self.client.get('/drill/new').get_data(as_text=True)
        self.assertIn('dem-bar', h)
        self.assertIn('Nové cvičení', h)
        self.assertEqual(h.count('id="board"'), 1)
        self.assertEqual(h.count('id="newDrillForm"'), 1)
        self.assertEqual(h.count('id="path_data"'), 1)
        self.assertIn('csrf_token', h)
        self.assertIn('/drill/save', h)        # create posts to save_drill

    def test_edit_drill_renders_mobile_layer_single_canvas(self):
        self._login('coach')
        h = self.client.get('/drill/%d/edit' % self.drill.id).get_data(as_text=True)
        self.assertIn('dem-bar', h)
        self.assertIn('Upravit cvičení', h)
        self.assertEqual(h.count('id="board"'), 1)
        self.assertEqual(h.count('id="newDrillForm"'), 1)
        self.assertIn('/update', h)            # edit posts to update_drill

    # ---- permissions ----
    def test_player_opens_editor_without_enabled_save(self):
        # Existing route behaviour: players MAY open the editor but cannot save.
        self._login('player')
        r = self.client.get('/drill/new')
        self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        self.assertIn('dem-bar', h)
        self.assertNotIn('btn-save-drill', h)  # enabled submit is coach-only

    def test_player_cannot_save(self):
        self._login('player')
        before = Drill.query.count()
        self.client.post('/drill/save', data={'name': 'X', 'category': 'Y'})
        self.assertEqual(Drill.query.count(), before)  # not created

    # ---- create vs edit semantics ----
    def test_coach_create_makes_one_drill(self):
        self._login('coach')
        before = Drill.query.count()
        r = self.client.post('/drill/save', data={'name': 'Nové', 'category': 'Útok', 'duration': '15', 'path_data': '[]'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Drill.query.count(), before + 1)
        created = Drill.query.filter_by(name='Nové').first()
        self.assertIsNotNone(created)
        self.assertEqual(created.team_id, self.tid)

    def test_coach_edit_updates_existing_only(self):
        self._login('coach')
        before = Drill.query.count()
        self.client.post('/drill/%d/update' % self.drill.id, data={'name': 'Bruslení 2', 'category': 'Rozbruslení', 'path_data': '[]'})
        self.assertEqual(Drill.query.count(), before)         # no new row
        self.assertEqual(db.session.get(Drill, self.drill.id).name, 'Bruslení 2')

    # ---- team isolation ----
    def test_edit_other_team_drill_blocked(self):
        self._login('coach')
        r = self.client.get('/drill/%d/edit' % self.other_drill.id)
        self.assertEqual(r.status_code, 302)

    def test_update_other_team_drill_blocked(self):
        self._login('coach')
        self.client.post('/drill/%d/update' % self.other_drill.id, data={'name': 'Hacked', 'category': 'x', 'path_data': '[]'})
        self.assertEqual(db.session.get(Drill, self.other_drill.id).name, 'Cizí')  # unchanged


if __name__ == '__main__':
    unittest.main()
