# -*- coding: utf-8 -*-
"""Lines editor — STATE/SAVE regression tests (Step A/B, written BEFORE any mobile
UI change). These pin the existing save semantics and empirically prove which of
the duplicated slot inputs (desktop #formations vs mobile .lines-swiper) the save
route persists. The mobile controller's sync-before-submit is validated against
this authoritative behavior.
"""
import unittest

from werkzeug.datastructures import MultiDict

from coach.app import app
from coach.extensions import db
from coach.models import LineAssignment, Player, Roster, Team, TeamKey
from coach.services.keys import hash_team_key


class LinesStateTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='HC Smíchov'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('ck')))
        # roster: 3 forwards, 2 defense, 1 goalie
        self.fwd = [Player(team_id=self.tid, name='F%d' % i, position='F') for i in range(3)]
        self.dfd = [Player(team_id=self.tid, name='D%d' % i, position='D') for i in range(2)]
        self.gk = Player(team_id=self.tid, name='G0', position='G')
        db.session.add_all(self.fwd + self.dfd + [self.gk]); db.session.flush()
        for p in self.fwd + self.dfd + [self.gk]:
            db.session.add(Roster(team_id=self.tid, player_id=p.id))
        self.other = Team(name='HC Soupeř'); db.session.add(self.other); db.session.flush()
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self, role='coach', tid=None):
        with self.client.session_transaction() as s:
            s['team_id'] = tid or self.tid; s['team_role'] = role; s['team_login'] = True

    def _assignments(self):
        return {a.slot: a.player_id for a in LineAssignment.query.filter_by(team_id=self.tid).all()}

    # ---- baseline save/state ----
    def test_save_persists_posted_assignments(self):
        self._login('coach')
        r = self.client.post('/lines', data={
            'L1LW': self.fwd[0].id, 'L1C': self.fwd[1].id, 'L1RW': self.fwd[2].id,
            'D1LD': self.dfd[0].id, 'D1RD': self.dfd[1].id, 'G1': self.gk.id,
        })
        self.assertEqual(r.status_code, 302)
        a = self._assignments()
        self.assertEqual(a.get('L1LW'), self.fwd[0].id)
        self.assertEqual(a.get('G1'), self.gk.id)

    def test_save_filters_non_roster_and_empty(self):
        self._login('coach')
        self.client.post('/lines', data={'L1LW': 999999, 'L1C': '', 'D1LD': self.dfd[0].id})
        a = self._assignments()
        self.assertNotIn('L1LW', a)          # non-roster id dropped
        self.assertNotIn('L1C', a)           # empty dropped
        self.assertEqual(a.get('D1LD'), self.dfd[0].id)

    def test_save_is_delete_all_recreate(self):
        self._login('coach')
        self.client.post('/lines', data={'L1LW': self.fwd[0].id})
        self.assertEqual(self._assignments().get('L1LW'), self.fwd[0].id)
        # second save without L1LW clears it (delete-all/recreate)
        self.client.post('/lines', data={'L2LW': self.fwd[1].id})
        a = self._assignments()
        self.assertNotIn('L1LW', a)
        self.assertEqual(a.get('L2LW'), self.fwd[1].id)

    # ---- STEP B: which duplicate input is authoritative? ----
    def test_duplicate_input_first_in_dom_is_authoritative(self):
        # A real browser submits BOTH the desktop (#formations, first in DOM) and
        # the swiper (.lines-swiper, second) copies of L1LW. Flask MultiDict.items()
        # yields the FIRST value per key -> the DESKTOP copy is what persists.
        self._login('coach')
        # ordered duplicate keys: desktop value first, swiper value second
        self.client.post('/lines', data=MultiDict([
            ('L1LW', str(self.fwd[0].id)),   # desktop copy (authoritative)
            ('L1LW', str(self.fwd[1].id)),   # swiper copy (ignored by items())
        ]))
        rows = LineAssignment.query.filter_by(team_id=self.tid, slot='L1LW').all()
        self.assertEqual(len(rows), 1)                       # only one row saved
        self.assertEqual(rows[0].player_id, self.fwd[0].id)  # the FIRST (desktop) value

    # ---- STEP #9: duplicate-player handling at the BACKEND (no rejection rule) ----
    def test_backend_accepts_unique_players(self):
        self._login('coach')
        self.client.post('/lines', data={
            'L1LW': self.fwd[0].id, 'L1C': self.fwd[1].id, 'L2LW': self.fwd[2].id,
        })
        a = self._assignments()
        self.assertEqual(a.get('L1LW'), self.fwd[0].id)
        self.assertEqual(a.get('L1C'), self.fwd[1].id)
        self.assertEqual(a.get('L2LW'), self.fwd[2].id)

    def test_backend_does_not_reject_real_duplicate(self):
        # The save route has NO duplicate-player rule; the same player posted to two
        # 5v5 slots is stored in both. (Duplicate detection is a CLIENT-side warning
        # panel only — documented, not changed here.)
        self._login('coach')
        self.client.post('/lines', data={'L1LW': self.fwd[0].id, 'L2LW': self.fwd[0].id})
        a = self._assignments()
        self.assertEqual(a.get('L1LW'), self.fwd[0].id)
        self.assertEqual(a.get('L2LW'), self.fwd[0].id)

    # ---- permissions / isolation ----
    def test_player_cannot_save(self):
        self._login('player')
        r = self.client.post('/lines', data={'L1LW': self.fwd[0].id})
        # coach_required redirects; no assignment persisted
        self.assertEqual(LineAssignment.query.filter_by(team_id=self.tid).count(), 0)

    def test_get_renders_for_team(self):
        self._login('coach')
        r = self.client.get('/lines')
        self.assertEqual(r.status_code, 200)
        self.assertIn('linesForm', r.get_data(as_text=True))

    # ---- mobile controller layer (structural / no-new-inputs guarantees) ----
    def test_mobile_layer_present_and_adds_no_slot_inputs(self):
        self._login('coach')
        h = self.client.get('/lines').get_data(as_text=True)
        # mobile partial present
        self.assertIn('lnm-bar', h)
        self.assertIn('lnm-tabs', h)
        self.assertIn('id="lnmPicker"', h)
        self.assertIn('id="lnmSave"', h)
        # the mobile controller script is loaded
        self.assertIn('lines_mobile.js', h)
        # CRITICAL: the mobile partial adds NO new form inputs (no third slot set).
        # Every slot input still appears exactly as many times as the existing
        # desktop+swiper duplication (2 for 5v5 line/goalie slots), never 3.
        self.assertEqual(h.count('name="L1LW"'), 2)   # desktop #formations + swiper only
        self.assertEqual(h.count('name="G1"'), 2)
        self.assertEqual(h.count('name="SUBF1"'), 1)  # subs single copy, unchanged
        # exactly one save form
        self.assertEqual(h.count('id="linesForm"'), 1)

    def test_line_tabs_generated_for_existing_units(self):
        self._login('coach')
        h = self.client.get('/lines').get_data(as_text=True)
        for label in ('1. lajna', '2. lajna', '3. lajna', '4. lajna', 'Brankáři', 'Náhradníci'):
            self.assertIn(label, h)

    def test_picker_markup_present(self):
        self._login('coach')
        h = self.client.get('/lines').get_data(as_text=True)
        self.assertIn('id="lnmPicker"', h)          # bottom sheet
        self.assertIn('id="lnmPickSearch"', h)      # search
        self.assertIn('id="lnmPickClear"', h)       # clear slot
        self.assertIn('id="lnmPickList"', h)        # player list
        self.assertIn('data-lnm-close', h)          # cancel affordance

    def test_mobile_edit_of_authoritative_slot_persists(self):
        # The mobile controller edits the #formations copy directly (proven the
        # authoritative one). Simulate that: post a #formations value and confirm
        # it persists — i.e. a mobile-edited value is the saved value. No sync path.
        self._login('coach')
        self.client.post('/lines', data=MultiDict([
            ('L1LW', str(self.fwd[2].id)),   # #formations (authoritative) value
            ('L1LW', ''),                    # swiper copy (second, stale) — ignored
        ]))
        self.assertEqual(self._assignments().get('L1LW'), self.fwd[2].id)


if __name__ == '__main__':
    unittest.main()
