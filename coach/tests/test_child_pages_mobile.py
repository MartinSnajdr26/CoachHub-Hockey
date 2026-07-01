# -*- coding: utf-8 -*-
"""Small child pages batch — mobile layers for Player Edit, Drill Category,
Drill Export Result, and Team Keys. Verifies each mobile layer renders, existing
routes/permissions/team-isolation are preserved, desktop markup remains, and no
sensitive data leaks.
"""
import unittest

from coach.app import app
from coach.extensions import db
from coach.models import Drill, Player, Team, TeamKey
from coach.services.keys import hash_team_key


def _base():
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                      SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')


class _Fixture(unittest.TestCase):
    def setUp(self):
        _base()
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='HC Smíchov'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('ck')))
        db.session.add(TeamKey(team_id=self.tid, role='player', key_hash=hash_team_key('pk')))
        self.other = Team(name='HC Soupeř'); db.session.add(self.other); db.session.flush()
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self, role='coach', tid=None):
        with self.client.session_transaction() as s:
            s['team_id'] = tid or self.tid; s['team_role'] = role; s['team_login'] = True


class PlayerEditMobileTest(_Fixture):
    def setUp(self):
        super().setUp()
        self.player = Player(team_id=self.tid, name='Martin Novák', position='F'); db.session.add(self.player)
        self.other_player = Player(team_id=self.other.id, name='Cizí Hráč', position='D'); db.session.add(self.other_player)
        db.session.commit()

    def test_renders_mobile_layer_single_form_csrf(self):
        self._login('coach')
        h = self.client.get('/edit_player/%d' % self.player.id).get_data(as_text=True)
        self.assertIn('pem-bar', h)
        self.assertIn('Upravit hráče', h)
        self.assertIn('csrf_token', h)
        self.assertEqual(h.count('name="position"'), 1)   # single edit form's select

    def test_coach_can_update(self):
        self._login('coach')
        self.client.post('/edit_player/%d' % self.player.id, data={'name': 'Nové Jméno', 'position': 'D'})
        p = db.session.get(Player, self.player.id)
        self.assertEqual(p.name, 'Nové Jméno')
        self.assertEqual(p.position, 'D')

    def test_player_role_cannot_access(self):
        self._login('player')
        self.assertEqual(self.client.get('/edit_player/%d' % self.player.id).status_code, 302)

    def test_other_team_player_blocked(self):
        self._login('coach')
        self.assertEqual(self.client.get('/edit_player/%d' % self.other_player.id).status_code, 302)


class DrillCategoryMobileTest(_Fixture):
    def setUp(self):
        super().setUp()
        db.session.add_all([
            Drill(team_id=self.tid, name='Bruslení A', category='Rozbruslení', duration=10),
            Drill(team_id=self.tid, name='Přihrávky B', category='Útok', duration=12),
            Drill(team_id=self.other.id, name='Cizí Rozbruslení', category='Rozbruslení'),
        ])
        db.session.commit()

    def test_renders_mobile_layer_and_only_category_drills(self):
        self._login('coach')
        h = self.client.get('/drills/Rozbruslení').get_data(as_text=True)
        self.assertIn('dcm-bar', h)
        self.assertIn('Bruslení A', h)
        self.assertNotIn('Přihrávky B', h)          # different category
        self.assertNotIn('Cizí Rozbruslení', h)     # other team
        self.assertIn('drill-fav', h)               # favorites control preserved
        self.assertIn('id="drillGrid"', h)          # desktop grid markup still present

    def test_player_no_coach_actions(self):
        self._login('player')
        h = self.client.get('/drills/Rozbruslení').get_data(as_text=True)
        self.assertIn('dcm-bar', h)
        self.assertIn('Bruslení A', h)
        self.assertNotIn('✏️ Upravit', h)           # coach-only edit link absent for player


class ExportResultMobileTest(_Fixture):
    def test_renders_mobile_layer_and_safe_download(self):
        self._login('coach')
        h = self.client.get('/drills/export_result?file=drills-x.pdf').get_data(as_text=True)
        self.assertIn('derm-root', h)
        self.assertIn('drills-x.pdf', h)
        self.assertIn('/exports/drills-x.pdf', h)     # download via existing protected route
        self.assertNotIn('/home/', h)                 # no filesystem path exposed
        self.assertNotIn('protected_exports', h)
        self.assertIn('<iframe', h)                   # desktop markup still present


class TeamKeysMobileTest(_Fixture):
    def test_coach_access_and_mobile_layer(self):
        self._login('coach')
        r = self.client.get('/team/keys')
        self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        self.assertIn('tkm-bar', h)
        self.assertIn('<table', h)                    # desktop history table remains
        self.assertIn('csrf_token', h)
        # no duplicate mobile app-bar / no duplicate rotation form
        self.assertEqual(h.count('class="tkm-bar"'), 1)
        self.assertEqual(h.count('name="which" value="coach"'), 1)

    def test_player_blocked(self):
        self._login('player')
        self.assertEqual(self.client.get('/team/keys').status_code, 302)

    def test_rotation_shows_key_once_not_in_url(self):
        self._login('coach')
        r = self.client.post('/team/keys', data={'which': 'coach'})
        self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        self.assertIn('ukáže se jen jednou', h)       # shown-once notice
        # the new key must never appear inside an href / URL
        import re
        codes = re.findall(r'<code>([^<]+)</code>', h)
        self.assertTrue(codes)
        for key in codes:
            self.assertNotIn('href="%s' % key, h)
            self.assertNotIn('?text=%s' % key, h)


if __name__ == '__main__':
    unittest.main()
