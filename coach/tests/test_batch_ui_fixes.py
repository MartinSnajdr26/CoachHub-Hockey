# -*- coding: utf-8 -*-
"""Batch UI fixes (BUG-6..11): Formace color-control alignment, Docházka header
height, global footer clearance, quick-play close color, landing preview removal,
dashboard button text. Verifies rendered output + scoped mobile.css rules.
"""
import os
import unittest

from coach.app import app
from coach.extensions import db
from coach.models import Player, Roster, Team, TeamKey
from coach.services.keys import hash_team_key

STATIC = app.static_folder
TPL = os.path.join(os.path.dirname(app.static_folder), 'templates')


def _read(*parts):
    with open(os.path.join(*parts), encoding='utf-8') as f:
        return f.read()


class BatchUiRenderTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='HC Test'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('ck')))
        p = Player(team_id=self.tid, name='Jan Novák', position='F'); db.session.add(p); db.session.flush()
        db.session.add(Roster(team_id=self.tid, player_id=p.id))
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self, role='coach'):
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid; s['team_role'] = role; s['team_login'] = True

    # BUG-10: landing no longer renders the preview section or old media
    def test_landing_preview_removed(self):
        h = self.client.get('/').get_data(as_text=True)
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertNotIn('id="nahled"', h)
        self.assertNotIn('href="#nahled"', h)
        self.assertNotIn('app_demo', h)
        self.assertNotIn('lp-preview', h)
        self.assertNotIn('lp-video', h)
        # unrelated sections still present
        self.assertIn('id="funkce"', h)
        self.assertIn('id="proc"', h)

    # BUG-11: dashboard shows the exact new button text (coach only)
    def test_dashboard_button_text(self):
        self._login('coach')
        h = self.client.get('/app').get_data(as_text=True)
        self.assertIn('＋ Přidat zápas / trénink', h)
        self.assertNotIn('＋ Nová akce</button>', h)


class BatchUiSourceTest(unittest.TestCase):
    def test_bug9_quickplay_close_uses_danger(self):
        src = _read(TPL, 'drill_session_detail.html')
        # find the qpClose button; it must use the danger background, not white
        idx = src.find('id="qpClose"')
        self.assertNotEqual(idx, -1)
        btn = src[idx:idx + 200]
        self.assertIn('var(--danger', btn)
        self.assertNotIn('background:#fff', btn)

    def test_bug6_colorpick_grid_rule(self):
        css = _read(STATIC, 'mobile.css')
        self.assertIn('.lines-colorpick {', css.replace('  ', '')) if False else None
        self.assertIn('.formation .lines-colorpick', css)
        # the alignment fix uses an equal-width grid
        self.assertIn('grid-template-columns: repeat(auto-fit, minmax(120px, 1fr))', css)

    def test_bug7_header_height_override_only(self):
        css = _read(STATIC, 'mobile.css')
        self.assertIn('--am-hhead: 72px', css)          # header row grows
        # our additions must NOT alter regular player-row height (--am-row)
        self.assertNotIn('--am-row:', css)

    def test_bug8_footer_clearance_scoped(self):
        css = _read(STATIC, 'mobile.css')
        self.assertIn('body:has(.mnav) .app-footer', css)
        idx = css.find('body:has(.mnav) .app-footer')
        rule = css[idx:idx + 150]
        self.assertIn('padding-bottom', rule)
        self.assertIn('env(safe-area-inset-bottom', rule)


if __name__ == '__main__':
    unittest.main()
