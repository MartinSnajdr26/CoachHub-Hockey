# -*- coding: utf-8 -*-
"""BUG-9: mobile Docházka matrix — the fixed player column and the scrollable
event columns must share ONE row height so rows align 1:1 (no drift, no marker
beside the wrong player). Verifies the shared --am-row model + 1:1 row rendering.
"""
import os
import re
import unittest
from datetime import date, timedelta

from coach.app import app
from coach.extensions import db
from coach.models import Player, Roster, Team, TeamKey, TrainingEvent
from coach.services.keys import hash_team_key

MOBILE_CSS = os.path.join(app.static_folder, 'mobile.css')


def _css():
    with open(MOBILE_CSS, encoding='utf-8') as f:
        return f.read()


class AttendanceAlignCssTest(unittest.TestCase):
    # 1. both panes driven by ONE shared row-height variable
    def test_shared_row_height_variable(self):
        css = _css()
        self.assertRegex(css, r'\.am-grid\s*\{[^}]*--am-row:\s*52px')

    # 2/6. the one-sided min-height hack (and any nth-child/manual offset) is gone
    def test_no_one_sided_min_height_or_nth_child(self):
        css = _css()
        self.assertNotRegex(css, r'\.am-lcell\s*\{[^}]*min-height:\s*52px')
        for line in css.splitlines():
            if any(sel in line for sel in ('am-lcell', 'am-mrow', 'am-cell')):
                self.assertNotIn('nth-child', line, 'no per-row pixel workaround allowed')

    # 5. header height stays on its OWN separate variable
    def test_header_height_independent(self):
        css = _css()
        self.assertIn('--am-hhead: 72px', css)     # header var
        self.assertIn('--am-row: 52px', css)       # data-row var (distinct)

    # 4. event cells centered within the shared height
    def test_event_cell_centered(self):
        css = _css()
        idx = css.find('.am-cell { display: flex')
        self.assertNotEqual(idx, -1)
        block = css[idx:idx + 130]
        self.assertIn('align-items: center', block)
        self.assertIn('justify-content: center', block)


class AttendanceAlignRenderTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='HC Test'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('ck')))
        # several players incl. a very long name; a couple of events -> matrix renders
        for n in ['Ada Novák', 'Bob Svoboda', 'Cyril Dvořák Nejdelší Jméno Pro Test Zalomení', 'Dan Černý']:
            p = Player(team_id=self.tid, name=n, position='F'); db.session.add(p); db.session.flush()
            db.session.add(Roster(team_id=self.tid, player_id=p.id))
        for d in range(2):
            db.session.add(TrainingEvent(team_id=self.tid, day=date.today() + timedelta(days=d),
                                         time='18:00', title='Trénink %d' % d, kind='training',
                                         source='coachhub_manual'))
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self):
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid; s['team_role'] = 'coach'; s['team_login'] = True

    # 1:1 correspondence: one fixed-column row (.am-lcell) per event-row (.am-mrow)
    def test_one_to_one_rows_and_metadata(self):
        self._login()
        h = self.client.get('/dochazka').get_data(as_text=True)
        n_left = h.count('class="am-lcell"')
        n_right = h.count('class="am-mrow"')
        self.assertEqual(n_left, 4)                 # 4 players in the fixed column
        self.assertEqual(n_left, n_right)           # exactly one event-row per player
        self.assertIn('am-sub', h)                  # 3. %/position metadata still rendered in the row
        self.assertIn('am-namebox', h)              # player name/initials preserved


if __name__ == '__main__':
    unittest.main()
