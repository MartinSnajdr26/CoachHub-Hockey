# -*- coding: utf-8 -*-
"""Mobile input/popup contrast (BUG-3/4/5): dark readable text on light fields.
Verifies affected pages render their inputs, mobile.css carries the scoped
dark-text + popup-title rules, and no broad global input-color rule was added.
"""
import os
import re
import unittest

from coach.app import app
from coach.extensions import db
from coach.models import Player, Roster, Team, TeamKey
from coach.services.keys import hash_team_key

MOBILE_CSS = os.path.join(app.static_folder, 'mobile.css')


def _css():
    with open(MOBILE_CSS, encoding='utf-8') as f:
        return f.read()


class MobileContrastRenderTest(unittest.TestCase):
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

    def test_pages_render_expected_inputs(self):
        self._login('coach')
        self.assertIn('class="plm-search"', self.client.get('/players').get_data(as_text=True))
        self.assertIn('name="name"', self.client.get('/players').get_data(as_text=True))     # new-player name field
        self.assertIn('class="rom-search"', self.client.get('/roster').get_data(as_text=True))
        self.assertIn('class="tam-search"', self.client.get('/dochazka').get_data(as_text=True))
        h = self.client.get('/attendance/import').get_data(as_text=True)
        self.assertIn('type="file"', h)                          # import upload input
        self.assertIn('aim-bar', h)                              # mobile scope hook present


class MobileContrastCssTest(unittest.TestCase):
    def test_input_classes_use_dark_field_text(self):
        css = _css()
        # every fixed input class must set color: var(--field-text ...) (dark), not var(--text)
        for cls in ('.tam-search', '.plm-search', '.plm-fld input', '.rom-search', '.pam-sheet-search'):
            # find the rule block for this selector and assert it carries --field-text
            idx = css.find(cls + ' {') if (cls + ' {') in css else css.find(cls + ',')
            self.assertNotEqual(idx, -1, 'selector missing: ' + cls)
            block = css[idx:idx + 400]
            self.assertIn('color: var(--field-text', block, cls + ' should use --field-text')

    def test_import_form_and_popup_rules_present_and_mobile_scoped(self):
        css = _css()
        self.assertIn('main:has(> .aim-bar) form[enctype]', css)          # BUG-4 import form
        self.assertIn('.help-dialog h3', css)                            # BUG-5 popup titles
        # popup-title fix must be inside a max-width media query (mobile-scoped)
        m = re.search(r'@media \(max-width: 768px\) \{(.*?)\n\}\s*$', css, re.S)
        # crude but effective: the help-dialog heading rule appears after a mobile @media opener
        self.assertTrue('.help-dialog h1' in css and '@media (max-width: 768px)' in css)
        help_idx = css.find('.help-dialog h1')
        prev_media = css.rfind('@media (max-width: 768px)', 0, help_idx)
        self.assertNotEqual(prev_media, -1, 'help-dialog title rule not under a mobile media query')

    def test_no_broad_global_input_color_rule_introduced(self):
        css = _css()
        # guard against an over-broad rule like `input { color: ... }` or `* { color }`
        self.assertNotRegex(css, r'(^|\})\s*input\s*\{[^}]*color')
        self.assertNotRegex(css, r'(^|\})\s*\*\s*\{[^}]*color')


if __name__ == '__main__':
    unittest.main()
