# -*- coding: utf-8 -*-
"""Permanent coach entry to /team/player-access in the mobile Team sheet.

Before this, a coach on a phone could reach the player-access overview only
while a request was pending, via the notification bell — with nothing waiting
there was no way in, so "who already has passkey access?" was unanswerable on
mobile. The sheet now carries the link permanently.

The contract:
  * shown for coaches ALWAYS, including pending_access_count == 0
  * annotated with the pending count when there is one
  * never shown to players
  * the route's own coach gate is unchanged — the link is navigation, not access
"""
import re
import os
import unittest

from coach.app import app
from coach.extensions import db
from coach.models import PlayerRegistrationRequest
from coach.tests.test_player_identity import IdentityTestBase

MOBILE_CSS = os.path.join(app.static_folder, 'mobile.css')
LABEL = 'Přístup hráčů'
URL = '/team/player-access'


def _msheet(html):
    """Just the mobile Team & settings sheet, so desktop nav can't satisfy an
    assertion meant for mobile."""
    start = html.find('id="mSheet"')
    if start < 0:
        return ''
    end = html.find('id="notifSheet"', start)
    return html[start:end if end > 0 else len(html)]


class MobileSheetLinkTest(IdentityTestBase):
    def _sheet_as_coach(self):
        self.login_coach()
        return _msheet(self.client.get('/app').get_data(as_text=True))

    def test_coach_sees_the_link_in_the_mobile_sheet(self):
        sheet = self._sheet_as_coach()
        self.assertIn(URL, sheet)
        self.assertIn(LABEL, sheet)
        self.assertIn('🔐', sheet)

    def test_link_is_present_with_zero_pending_requests(self):
        """The regression that motivated this: no pending request, still reachable."""
        self.assertEqual(PlayerRegistrationRequest.query.count(), 0)
        sheet = self._sheet_as_coach()
        self.assertIn(URL, sheet)
        # ...and with no count annotation
        self.assertNotRegex(sheet, re.escape(LABEL) + r'\s*\(\d+\)')

    def test_link_is_present_when_no_player_ever_requested_access(self):
        from coach.models import Player
        Player.query.delete()
        db.session.commit()
        self.assertIn(URL, self._sheet_as_coach())

    def test_pending_count_is_shown_next_to_the_label(self):
        self.login_player_key()
        self.claim(self.alice_id)
        sheet = self._sheet_as_coach()
        self.assertIn(URL, sheet)
        self.assertRegex(sheet, re.escape(LABEL) + r'\s*\(1\)')

    def test_pending_count_tracks_multiple_requests(self):
        self.login_player_key()
        self.claim(self.alice_id)
        second = app.test_client()
        self.key_login(self.tid, 'player', 'player-key-alpha', second)
        second.post('/player/onboarding/claim', data={'player_id': self.bob_id})
        self.assertEqual(len(
            __import__('coach.services.player_identity', fromlist=['x'])
            .pending_requests_for_team(self.tid)), 2)
        self.assertRegex(self._sheet_as_coach(), re.escape(LABEL) + r'\s*\(2\)')

    def test_player_does_not_see_the_link(self):
        self.login_verified(self.alice_id)
        sheet = _msheet(self.client.get('/app').get_data(as_text=True))
        self.assertNotIn(URL, sheet)
        self.assertNotIn(LABEL, sheet)

    def test_link_sits_inside_the_existing_sheet_grid(self):
        """Preserves the sheet's visual style: a plain grid item like its
        siblings, not a new wide/danger row."""
        sheet = self._sheet_as_coach()
        grid = sheet[sheet.find('msheet-grid'):]
        anchor = re.search(r'<a href="' + re.escape(URL) + r'"[^>]*>(.*?)</a>', grid, re.S)
        self.assertIsNotNone(anchor, 'link is not inside .msheet-grid')
        self.assertIn('msheet-ic', anchor.group(1))
        full = anchor.group(0)
        self.assertNotIn('msheet-wide', full)
        self.assertNotIn('is-danger', full)


class RouteSecurityUnchangedTest(IdentityTestBase):
    """The link is navigation only — the route keeps its own gate."""

    def test_coach_can_open_the_page(self):
        self.login_coach()
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Přístup hráčů', resp.get_data(as_text=True))

    def test_verified_player_is_refused_by_url(self):
        self.login_verified(self.alice_id)
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn('/team/player-access', resp.headers.get('Location', ''))

    def test_shared_key_session_is_refused_by_url(self):
        self.login_player_key()
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/player/onboarding', resp.headers['Location'])

    def test_anonymous_is_refused_by_url(self):
        resp = app.test_client().get(URL)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/team/auth', resp.headers['Location'])

    def test_player_cannot_approve_via_the_page_endpoints(self):
        self.login_player_key()
        self.claim(self.alice_id)
        req = self.latest_request(self.alice_id)
        attacker = app.test_client()
        self.login_verified(self.bob_id, client=attacker)
        resp = attacker.post('/team/player-access/%d/approve' % req.id)
        self.assertEqual(resp.status_code, 302)
        db.session.refresh(req)
        self.assertEqual(req.status, PlayerRegistrationRequest.STATUS_PENDING)


class PlayerAccessNotHiddenOnMobileTest(IdentityTestBase):
    """§8 — the page must stay visible; no unscoped .pk-wrap hide may return."""

    def test_page_renders_its_wrapper(self):
        self.login_coach()
        html = self.client.get(URL).get_data(as_text=True)
        self.assertIn('pk-wrap', html)

    def test_no_unscoped_rule_hides_pk_wrap(self):
        css = re.sub(r'/\*.*?\*/', '', open(MOBILE_CSS, encoding='utf-8').read(), flags=re.S)
        offenders = []
        for selector, decls in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
            if 'pk-wrap' not in selector:
                continue
            if not re.search(r'display\s*:\s*none', decls):
                continue
            if 'pkm-root' not in selector and 'pokladna' not in selector:
                offenders.append(selector.strip())
        self.assertEqual(offenders, [], 'unscoped .pk-wrap hide rule(s): %s' % offenders)


if __name__ == '__main__':
    unittest.main()
