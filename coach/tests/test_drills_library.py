# -*- coding: utf-8 -*-
"""Mobile Practice Library: additive /drills context is team-scoped, read-only,
and the desktop category grid still renders unchanged.

The desktop template (drills_categories.html) renders only category names; the
mobile partial (_drills_library.html) renders individual drill names and the
coach-only FAB. We use those distinct markers to tell the two layers apart in
one response, since both are emitted on the same /drills route.
"""
import unittest

from coach.app import app
from coach.extensions import db
from coach.models import Drill, Team, TeamKey
from coach.services.keys import hash_team_key


class DrillsLibraryTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        # Team A (the one we log into)
        self.team = Team(name='HC Smíchov'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('ck')))
        db.session.add_all([
            Drill(team_id=self.tid, name='Bruslení vpřed', category='Rozbruslení', description='Základní bruslení', duration=10),
            Drill(team_id=self.tid, name='Přesilovka 5v4', category='Útok', description='Rozehrání PP', duration=15),
        ])
        # Team B (must never leak into Team A's library)
        self.other = Team(name='HC Soupeř'); db.session.add(self.other); db.session.flush()
        db.session.add(Drill(team_id=self.other.id, name='Tajné cvičení soupeře', category='Obrana'))
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self, role='coach'):
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid; s['team_role'] = role; s['team_login'] = True

    # ---- renders + desktop unchanged ----
    def test_drills_renders_and_desktop_grid_intact(self):
        self._login('coach')
        r = self.client.get('/drills')
        self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        # Desktop category grid still present (unchanged desktop rendering).
        self.assertIn('id="catGrid"', h)
        self.assertIn('Rozbruslení', h)  # category name (desktop + mobile chip)
        # Mobile library present.
        self.assertIn('dlm-root', h)
        self.assertIn('Knihovna cvičení', h)

    # ---- mobile list reads the additive team-scoped drill context ----
    def test_mobile_list_shows_own_team_drills(self):
        self._login('coach')
        h = self.client.get('/drills').get_data(as_text=True)
        self.assertIn('Bruslení vpřed', h)
        self.assertIn('Přesilovka 5v4', h)

    # ---- tenant isolation ----
    def test_other_team_drill_not_exposed(self):
        self._login('coach')
        h = self.client.get('/drills').get_data(as_text=True)
        self.assertNotIn('Tajné cvičení soupeře', h)

    # ---- permissions: coach sees create/secondary actions, player does not ----
    def test_coach_sees_fab_and_actions(self):
        self._login('coach')
        h = self.client.get('/drills').get_data(as_text=True)
        self.assertIn('dlm-fab', h)
        self.assertIn('dlm-kebab', h)

    def test_player_can_view_but_no_coach_controls(self):
        self._login('player')
        r = self.client.get('/drills')
        self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        # Player may browse the library...
        self.assertIn('Bruslení vpřed', h)
        # ...but coach-only create / per-card actions are absent.
        self.assertNotIn('dlm-fab', h)
        self.assertNotIn('dlm-kebab', h)

    # ---- mobile sub-navigation makes select + sessions (+ detail) reachable ----
    def test_mobile_subnav_links_present(self):
        self._login('coach')
        h = self.client.get('/drills').get_data(as_text=True)
        self.assertIn('dlm-subnav', h)
        self.assertIn('Uložené tréninky', h)              # -> drill_sessions -> detail
        self.assertIn('Vybrat', h)                        # -> drills_select
        self.assertIn('/drill-sessions', h)
        self.assertIn('/drills/select', h)

    def test_mobile_subnav_visible_to_player(self):
        # Both target pages are viewable by players (export stays coach-gated).
        self._login('player')
        h = self.client.get('/drills').get_data(as_text=True)
        self.assertIn('dlm-subnav', h)


if __name__ == '__main__':
    unittest.main()
