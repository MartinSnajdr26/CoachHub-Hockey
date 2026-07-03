# -*- coding: utf-8 -*-
"""Saved Training Sessions redesign: compact library cards + overflow menu.
Verifies the new card structure, that the full drill list is gone, the primary
action is exactly "Otevřít", all secondary actions live in the overflow menu,
delete stays protected, and routes/hrefs are unchanged.
"""
import re
import unittest

from coach.app import app
from coach.extensions import db
from coach.models import Drill, Team, TeamKey, TrainingSession
from coach.services.keys import hash_team_key


class SessionsRedesignTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='HC Test'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('ck')))
        self.d1 = Drill(team_id=self.tid, name='Bruslení', category='Rozbruslení', duration=10)
        self.d2 = Drill(team_id=self.tid, name='Přihrávky', category='Útok', duration=15)
        db.session.add_all([self.d1, self.d2]); db.session.flush()
        # a session WITH a pdf + 2 drills
        self.sess = TrainingSession(team_id=self.tid, title='Tréninková jednotka A',
                                    filename='drills-x.pdf', drill_ids='%d,%d' % (self.d1.id, self.d2.id))
        # a folder-only session (no PDF)
        self.folder = TrainingSession(team_id=self.tid, title='Složka bez PDF',
                                      filename='-', drill_ids='%d' % self.d1.id)
        db.session.add_all([self.sess, self.folder]); db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self, role='coach'):
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid; s['team_role'] = role; s['team_login'] = True

    def _html(self):
        r = self.client.get('/drill-sessions')
        self.assertEqual(r.status_code, 200)
        return r.get_data(as_text=True)

    # 1. title
    def test_card_renders_title(self):
        self._login('coach')
        self.assertIn('Tréninková jednotka A', self._html())

    # 2. drill count
    def test_card_renders_drill_count(self):
        self._login('coach')
        h = self._html()
        self.assertIn('2 cvičení', h)          # sess has 2 resolvable drills
        self.assertIn('25 min', h)             # 10 + 15 total duration

    # 3. full drill list NOT rendered
    def test_no_full_drill_list(self):
        self._login('coach')
        h = self._html()
        self.assertNotIn('Obsahuje cvičení', h)          # old list heading gone
        self.assertNotIn('>Bruslení<', h)                # individual drill names not listed
        self.assertNotIn('>Přihrávky<', h)

    # 4. primary action text exactly "Otevřít"
    def test_primary_action_text(self):
        self._login('coach')
        h = self._html()
        self.assertIn('>Otevřít</a>', h)
        self.assertNotIn('Otevřít stránku tréninku', h)

    # 5. overflow menu contains all secondary actions
    def test_overflow_menu_actions(self):
        self._login('coach')
        h = self._html()
        self.assertIn('tsl-menu', h)
        self.assertIn('Stáhnout PDF', h)
        self.assertIn('Sdílet soubor', h)
        self.assertIn('Sdílet stránku', h)
        self.assertIn('🗑 Smazat', h)
        self.assertIn('aria-label="Další akce', h)       # accessible overflow button
        # folder-only session offers "Vygenerovat PDF" in its menu
        self.assertIn('Vygenerovat PDF', h)

    # 6. delete remains present + protected (existing confirm flow + route)
    def test_delete_present_and_protected(self):
        self._login('coach')
        h = self._html()
        self.assertIn('class="form-confirm"', h)
        self.assertIn('data-message="Smazat', h)
        self.assertIn('/drill-sessions/delete/%d' % self.sess.id, h)

    # 7. routes / hrefs unchanged
    def test_routes_unchanged(self):
        self._login('coach')
        h = self._html()
        self.assertIn('/drill-sessions/%d' % self.sess.id, h)        # detail (Otevřít)
        self.assertIn('/exports/drills-x.pdf', h)                     # download via protected route
        self.assertIn('api.whatsapp.com/send', h)                     # share page

    # 8. same card data regardless of viewport (single responsive grid) + mobile app bar
    def test_single_grid_and_mobile_appbar(self):
        self._login('coach')
        h = self._html()
        self.assertEqual(h.count('class="tsl-grid"'), 1)
        self.assertIn('tsm-bar', h)                                   # mobile app bar included

    # 9. no duplicate secondary actions outside the menu
    def test_no_duplicate_actions_outside_menu(self):
        self._login('coach')
        h = self._html()
        # "Stáhnout PDF" appears exactly once (inside the menu), not duplicated on the card
        self.assertEqual(h.count('Stáhnout PDF'), 1)
        self.assertEqual(h.count('Sdílet soubor'), 1)

    # player still sees the page but no coach-only delete/generate
    def test_player_no_coach_actions(self):
        self._login('player')
        h = self._html()
        self.assertIn('Tréninková jednotka A', h)
        self.assertNotIn('🗑 Smazat', h)
        self.assertNotIn('Vygenerovat PDF', h)


if __name__ == '__main__':
    unittest.main()
