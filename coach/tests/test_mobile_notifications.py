# -*- coding: utf-8 -*-
"""Notifications must be reachable on mobile.

The desktop bell lives in `.header-bottom`, which mobile.css hides below 768px,
and neither the bottom nav nor the Tým sheet had an entry for it — so on a
phone there was no way to see notifications at all. A mobile-only bell in
`.header-top` opens a `.msheet` with the same items.

Desktop must be untouched: the button carries inline `display:none` and is
revealed only inside the mobile media query.
"""
import json
import os
import re
import unittest
from datetime import date, datetime, timedelta

from coach.app import app
from coach.extensions import db
from coach.models import AuditEvent, TrainingEvent
from coach.tests.test_player_identity import IdentityTestBase

MOBILE_CSS = os.path.join(app.static_folder, 'mobile.css')
MOBILENAV_JS = os.path.join(app.static_folder, 'mobilenav.js')


def _split_mobile_css():
    """(inside, outside) — text within the max-width:768px blocks, and the rest.

    Lets a test assert both "this rule exists on mobile" and "this rule does not
    leak to desktop", which is the whole contract for a mobile-only addition.
    """
    css = re.sub(r'/\*.*?\*/', '', open(MOBILE_CSS, encoding='utf-8').read(), flags=re.S)
    inside, outside, i = [], [], 0
    while True:
        m = re.search(r'@media[^{]*max-width:\s*768px[^{]*\{', css[i:])
        if not m:
            outside.append(css[i:])
            return '\n'.join(inside), '\n'.join(outside)
        outside.append(css[i:i + m.start()])
        start = i + m.end()
        depth, j = 1, start
        while j < len(css) and depth:
            if css[j] == '{':
                depth += 1
            elif css[j] == '}':
                depth -= 1
            j += 1
        inside.append(css[start:j - 1])
        i = j


class BellAssetsTest(unittest.TestCase):
    def test_bell_is_revealed_only_on_mobile(self):
        inside, outside = _split_mobile_css()
        self.assertRegex(inside, r'\.mnav-bell\s*\{[^}]*display:\s*inline-flex')
        self.assertNotIn('.mnav-bell', outside)

    def test_wordmark_is_only_hidden_on_mobile(self):
        """Making room for the bell must not touch the desktop header."""
        inside, outside = _split_mobile_css()
        self.assertRegex(inside, r'\.header-top \.app-brand\s*\{[^}]*display:\s*none')
        self.assertNotIn('.app-brand', outside)

    def test_sheet_is_wired(self):
        js = open(MOBILENAV_JS, encoding='utf-8').read()
        self.assertIn("wireSheet('mnavBell', 'notifSheet')", js)
        self.assertIn('.notif-list a', js)   # tapping an item closes the sheet


class BellRenderingTest(IdentityTestBase):
    def _seed_notifications(self):
        db.session.add(TrainingEvent(team_id=self.tid, day=date.today(),
                                     time='18:00', title='Trénink A-tým', kind='training'))
        db.session.add(AuditEvent(team_id=self.tid, event='message', role='coach',
                                  created_at=datetime.utcnow(),
                                  meta=json.dumps({'text': 'Sraz dřív', 'role': 'coach'})))
        db.session.commit()

    def test_coach_gets_bell_and_sheet(self):
        self.login_coach()
        html = self.client.get('/app').get_data(as_text=True)
        self.assertIn('id="mnavBell"', html)
        self.assertIn('id="notifSheet"', html)
        self.assertIn('aria-controls="notifSheet"', html)

    def test_bell_is_hidden_inline_so_desktop_is_unaffected(self):
        self.login_coach()
        html = self.client.get('/app').get_data(as_text=True)
        self.assertIn('id="mnavBell" style="display:none"', html)
        self.assertIn('id="notifSheet"', html)
        self.assertRegex(html, r'id="notifSheet"[^>]*style="display:none"')

    def test_notifications_render_in_the_sheet(self):
        self.login_coach()
        self._seed_notifications()
        html = self.client.get('/app').get_data(as_text=True)
        sheet = html.split('id="notifSheet"', 1)[1].split('</div>\n    </div>', 1)[0]
        self.assertIn('Trénink A-tým', sheet)
        self.assertIn('notif-list', sheet)
        self.assertIn('mnav-bell-badge', html)

    def test_empty_state_when_nothing_to_report(self):
        self.login_coach()
        html = self.client.get('/app').get_data(as_text=True)
        self.assertIn('Žádné nové notifikace', html)
        self.assertNotIn('mnav-bell-badge', html)   # no badge at zero

    def test_verified_player_also_gets_the_bell(self):
        self.login_verified(self.alice_id)
        html = self.client.get('/app').get_data(as_text=True)
        self.assertIn('id="mnavBell"', html)

    def test_onboarding_only_session_gets_no_bell(self):
        """Same rule as the rest of the nav — nothing app-level for a shared key."""
        self.login_player_key()
        html = self.client.get('/player/onboarding').get_data(as_text=True)
        self.assertNotIn('id="mnavBell"', html)
        self.assertNotIn('id="notifSheet"', html)
        self.assertNotIn('class="mnav"', html)
        self.assertIn('pk-wrap', html)              # ...but the page still renders

    def test_logged_out_visitor_gets_no_bell(self):
        html = self.client.get('/team/auth').get_data(as_text=True)
        self.assertNotIn('id="mnavBell"', html)

    def test_bell_content_matches_the_desktop_bell(self):
        """One source of truth: both read the same `notifications` context."""
        self.login_coach()
        self._seed_notifications()
        html = self.client.get('/app').get_data(as_text=True)
        desktop = html.count('Dnes Trénink: Trénink A-tým')
        self.assertEqual(desktop, 2, 'expected the item in both bells')


if __name__ == '__main__':
    unittest.main()
