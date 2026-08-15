# -*- coding: utf-8 -*-
"""Onboarding must be visible on mobile (.pk-wrap class-collision regression).

The bug: `.pk-* ` is used by THREE unrelated screens — Pokladna
(pk = pokladna), player onboarding and the coach's player-access inbox
(pk = passkey). Only Pokladna has a mobile replacement (`.pkm-root`), so
mobile.css hid the desktop wrapper with an unscoped

    @media (max-width: 768px) { .pk-wrap { display: none !important; } }

which also blanked the two responsive .pk-* pages on phones: header, empty
main, footer. Nothing was wrong with their markup or with playerauth.css.

These tests therefore guard two things:
  * the CSS rule stays SCOPED to the page that owns .pkm-root, and
  * the onboarding content is never conditionally omitted server-side.

An HTTP test cannot prove visual rendering — it proves the content is in the
document and that no stylesheet rule hides it. The layout itself was checked
manually in a real browser at phone widths.
"""
import os
import re
import unittest

from coach.app import app
from coach.extensions import db
from coach.models import PasskeyCredential, Player, PlayerRegistrationRequest
from coach.tests.test_player_identity import IdentityTestBase

MOBILE_CSS = os.path.join(app.static_folder, 'mobile.css')
PLAYERAUTH_CSS = os.path.join(app.static_folder, 'playerauth.css')


def _strip_comments(css):
    return re.sub(r'/\*.*?\*/', '', css, flags=re.S)


def _rules(css):
    """(selector, declarations) for every flat rule, including inside @media."""
    return re.findall(r'([^{}]+)\{([^{}]*)\}', _strip_comments(css))


def _hides(decls):
    return re.search(r'display\s*:\s*none', decls) is not None


class PkWrapHideRuleIsScopedTest(unittest.TestCase):
    """The actual root cause — a CSS-level guard, not a rendering claim."""

    def test_no_unscoped_rule_hides_pk_wrap(self):
        offenders = []
        for selector, decls in _rules(open(MOBILE_CSS, encoding='utf-8').read()):
            if 'pk-wrap' not in selector or not _hides(decls):
                continue
            # A rule may hide .pk-wrap only when tied to the mobile Pokladna
            # component that replaces it, or to the pokladna page itself.
            if 'pkm-root' not in selector and 'pokladna' not in selector:
                offenders.append(selector.strip())
        self.assertEqual(offenders, [], 'unscoped .pk-wrap hide rule(s) would '
                                        'blank onboarding on mobile: %s' % offenders)

    def test_pokladna_desktop_wrapper_is_still_hidden_on_mobile(self):
        """The scoping must not regress Pokladna into showing both UIs."""
        css = _strip_comments(open(MOBILE_CSS, encoding='utf-8').read())
        self.assertRegex(css, r'\.pkm-root\s*~\s*\.pk-wrap\s*\{[^}]*display\s*:\s*none')

    def test_playerauth_layout_is_mobile_first(self):
        """No max-width query may gate the onboarding layout into existence."""
        css = _strip_comments(open(PLAYERAUTH_CSS, encoding='utf-8').read())
        self.assertNotIn('max-width: 768px', css)
        self.assertIn('@media (min-width: 769px)', css)
        for selector, decls in _rules(css):
            if 'pk-wrap' in selector:
                self.assertFalse(_hides(decls), 'playerauth.css hides .pk-wrap')


class OnboardingContentIsAlwaysRenderedTest(IdentityTestBase):
    """Every state must ship its content — no mobile/onboarding-only omission."""

    def _page(self):
        resp = self.client.get('/player/onboarding')
        self.assertEqual(resp.status_code, 200)
        return resp.get_data(as_text=True)

    def _approve_latest(self, player_id):
        req = self.latest_request(player_id)
        coach = app.test_client()
        self.login_coach(client=coach)
        resp = coach.post('/team/player-access/%d/approve' % req.id)
        self.assertIn(resp.status_code, (200, 302))
        return req

    # -- state: identity selection ------------------------------------
    def test_selection_state_renders_roster_and_cta(self):
        self.login_player_key()
        html = self._page()
        self.assertIn('pk-wrap', html)
        self.assertIn('Ověření hráče', html)
        self.assertIn('Kdo jsi?', html)
        self.assertIn('Alice Nováková', html)
        self.assertIn('Bob Svoboda', html)
        self.assertIn('To jsem já', html)
        self.assertIn('pk-search', html)

    def test_selection_state_excludes_other_teams_players(self):
        self.login_player_key()
        self.assertNotIn('Beta Hráč', self._page())

    # -- state: pending -----------------------------------------------
    def test_pending_state_renders_status_and_actions(self):
        self.login_player_key()
        self.claim(self.alice_id)
        html = self._page()
        self.assertIn('Čeká na schválení trenérem', html)
        self.assertIn('Zkontrolovat stav', html)
        self.assertIn('Zrušit žádost', html)
        self.assertIn('Alice Nováková', html)
        # the roster picker is intentionally replaced, not merely hidden
        self.assertNotIn('Kdo jsi?', html)

    # -- state: approved (the critical one) ---------------------------
    def test_approved_state_renders_create_passkey_button(self):
        self.login_player_key()
        self.claim(self.alice_id)
        self._approve_latest(self.alice_id)
        html = self._page()
        self.assertIn('Trenér přístup schválil', html)
        self.assertIn('Vytvořit passkey', html)
        self.assertIn('data-pk-register', html)
        # the button must be a real enabled control, not a disabled stub
        self.assertNotIn('data-pk-register disabled', html)

    def test_approved_state_wires_both_ceremony_urls(self):
        self.login_player_key()
        self.claim(self.alice_id)
        self._approve_latest(self.alice_id)
        html = self._page()
        self.assertIn('/passkey/register/options', html)
        self.assertIn('/passkey/register/verify', html)
        self.assertIn('passkey.js', html)

    def test_approved_state_has_the_error_message_target(self):
        """WebAuthn errors render into #pkMsg — it must exist in the document."""
        self.login_player_key()
        self.claim(self.alice_id)
        self._approve_latest(self.alice_id)
        html = self._page()
        self.assertIn('id="pkMsg"', html)
        self.assertIn('data-pk-msg="pkMsg"', html)
        self.assertIn('aria-live="polite"', html)

    # -- state: rejected / expired ------------------------------------
    def test_rejected_state_renders(self):
        self.login_player_key()
        self.claim(self.alice_id)
        req = self.latest_request(self.alice_id)
        coach = app.test_client()
        self.login_coach(client=coach)
        coach.post('/team/player-access/%d/reject' % req.id)
        self.assertIn('Žádost byla zamítnuta', self._page())

    # -- state: empty roster ------------------------------------------
    def test_empty_roster_state_renders(self):
        self.login_player_key()
        Player.query.filter_by(team_id=self.tid).delete()
        db.session.commit()
        html = self._page()
        self.assertIn('Zatím tu nejsou žádní hráči k registraci', html)
        self.assertIn('pk-empty', html)

    # -- always present -----------------------------------------------
    def test_logout_escape_hatch_is_always_present(self):
        """Nav is inert for a shared-key session, so the page owns the way out."""
        self.login_player_key()
        for stage in ('initial', 'pending'):
            if stage == 'pending':
                self.claim(self.alice_id)
            html = self._page()
            self.assertIn('Odhlásit', html)
            self.assertIn('/team/logout', html)

    def test_content_sits_inside_main(self):
        """Guards against the wrapper escaping <main> and its mobile padding."""
        self.login_player_key()
        html = self._page()
        main = html.split('<main>', 1)[1].split('</main>', 1)[0]
        self.assertIn('pk-wrap', main)
        self.assertIn('Ověření hráče', main)

    def test_onboarding_session_gets_no_app_nav_but_keeps_content(self):
        """§4 — hiding the mobile nav must not take the page content with it."""
        self.login_player_key()
        html = self._page()
        self.assertNotIn('class="mnav"', html)      # nav correctly suppressed
        self.assertIn('pk-wrap', html)              # content still there


class PlayerAccessPageAlsoUsesPkWrapTest(IdentityTestBase):
    """The coach-facing screen hit by the same collision."""

    def test_player_access_page_renders_its_wrapper(self):
        self.login_coach()
        resp = self.client.get('/team/player-access')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('pk-wrap', html)
        self.assertIn('Přístup hráčů', html)


class AuthorizationUnchangedTest(IdentityTestBase):
    """§3 — the presentation fix must not have moved any gate."""

    def test_shared_key_still_cannot_reach_the_app(self):
        self.login_player_key()
        for path in ('/app', '/dochazka', '/attendance', '/players'):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 302, path)
            self.assertIn('/player/onboarding', resp.headers['Location'], path)

    def test_pending_request_still_grants_nothing(self):
        self.login_player_key()
        self.claim(self.alice_id)
        self.assertIsNone(self.session_value('player_id'))
        resp = self.client.get('/app')
        self.assertEqual(resp.status_code, 302)

    def test_approved_without_passkey_is_still_onboarding_only(self):
        self.login_player_key()
        self.claim(self.alice_id)
        req = self.latest_request(self.alice_id)
        coach = app.test_client()
        self.login_coach(client=coach)
        coach.post('/team/player-access/%d/approve' % req.id)
        self.assertIsNone(self.session_value('player_id'))
        resp = self.client.get('/app')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/player/onboarding', resp.headers['Location'])

    def test_verified_passkey_reaches_the_app(self):
        self.onboard_fully(self.alice_id)
        self.assertEqual(self.session_value('player_id'), self.alice_id)
        self.assertEqual(self.client.get('/app').status_code, 200)


if __name__ == '__main__':
    unittest.main()
