# -*- coding: utf-8 -*-
"""Resumable onboarding: the claim survives the session, not the other way round.

Previously the claim token lived in the Flask session, so a player who closed
the app while waiting for coach approval lost the only proof that their browser
owned the approved request. The token now rides in its own persistent HttpOnly
cookie, so the browser may be closed and reopened.

The security contract these tests pin down:

    the resume cookie continues ONE registration request
    it is NOT authentication, NOT the shared player key, and NOT an app session

so it must never reach the app, never expose the roster, never survive
activation / rejection / expiry / cancellation, and never be usable by a
different browser.
"""
import unittest
from datetime import datetime, timedelta

from coach.app import app
from coach.extensions import db
from coach.models import PasskeyCredential, Player, PlayerRegistrationRequest
from coach.services import onboarding_resume as resume
from coach.services import player_identity as ident
from coach.tests.test_player_identity import (PLAYER_KEY_A, IdentityTestBase)

COOKIE = 'chh_onboarding'


class ResumeBase(IdentityTestBase):
    def _set_cookie_headers(self, resp):
        return resp.headers.getlist('Set-Cookie')

    def _onboarding_cookie_header(self, resp):
        for h in self._set_cookie_headers(resp):
            if h.startswith(COOKIE + '='):
                return h
        return None

    def start_claim(self, player_id=None):
        """Player key -> pick a player. Returns the raw resume token."""
        self.login_player_key()
        resp = self.claim(player_id or self.alice_id)
        self.assertIn(resp.status_code, (200, 302))
        token = self.resume_cookie()
        self.assertTrue(token)
        return token

    def approve_latest(self, player_id=None):
        req = self.latest_request(player_id or self.alice_id)
        coach = app.test_client()
        self.login_coach(client=coach)
        coach.post('/team/player-access/%d/approve' % req.id)
        db.session.refresh(req)
        return req

    def returning_browser(self, token):
        """A browser holding ONLY the resume cookie — no Flask session at all."""
        c = app.test_client()
        c.set_cookie(COOKIE, token, domain='localhost')
        return c


# =========================================================================
class CookieIssuanceTest(ResumeBase):
    """§3/§24 — the cookie's security properties, not its exact bytes."""

    def test_claim_sets_an_httponly_resume_cookie(self):
        self.login_player_key()
        resp = self.claim(self.alice_id)
        header = self._onboarding_cookie_header(resp)
        self.assertIsNotNone(header, 'no resume cookie was set')
        self.assertIn('HttpOnly', header)
        self.assertIn('SameSite=Lax', header)
        self.assertIn('Path=/', header)
        self.assertIn('Max-Age=', header)
        self.assertNotIn('Domain=', header)      # host-only

    def test_cookie_is_secure_under_production_config(self):
        original = app.config['SESSION_COOKIE_SECURE']
        app.config['SESSION_COOKIE_SECURE'] = True
        try:
            self.login_player_key()
            header = self._onboarding_cookie_header(self.claim(self.alice_id))
            self.assertIn('Secure', header)
        finally:
            app.config['SESSION_COOKIE_SECURE'] = original

    def test_dev_config_stays_testable_over_http(self):
        original = app.config['SESSION_COOKIE_SECURE']
        app.config['SESSION_COOKIE_SECURE'] = False
        try:
            self.login_player_key()
            header = self._onboarding_cookie_header(self.claim(self.alice_id))
            self.assertNotIn('Secure', header)
        finally:
            app.config['SESSION_COOKIE_SECURE'] = original

    def test_cookie_lifetime_is_configured_not_hardcoded(self):
        self.assertGreater(app.config['PLAYER_ONBOARDING_COOKIE_MAX_AGE'], 0)
        self.assertEqual(resume.cookie_name(), app.config['PLAYER_ONBOARDING_COOKIE_NAME'])

    def test_token_is_high_entropy_and_only_stored_hashed(self):
        token = self.start_claim()
        self.assertGreaterEqual(len(token), 40)
        req = self.latest_request(self.alice_id)
        self.assertNotEqual(req.claim_token_hash, token)
        self.assertEqual(req.claim_token_hash, ident.hash_claim_token(token))
        # the raw token appears nowhere in the row
        for col in ('claimed_name', 'claim_token_hash'):
            self.assertNotIn(token, str(getattr(req, col) or ''))

    def test_token_never_reaches_the_page_or_the_audit_log(self):
        from coach.models import AuditEvent
        token = self.start_claim()
        html = self.client.get('/player/onboarding').get_data(as_text=True)
        self.assertNotIn(token, html)
        events = AuditEvent.query.all()
        self.assertTrue(events, 'expected the claim to be audited at all')
        for ev in events:
            self.assertNotIn(token, str(ev.meta or ''))
            self.assertNotIn(token, str(ev.event or ''))


# =========================================================================
class SurvivesSessionLossTest(ResumeBase):
    """§1/§23 — the actual feature: close the app, come back later."""

    def test_pending_claim_is_recovered_after_the_session_is_gone(self):
        token = self.start_claim()
        self.drop_session_keep_cookie()
        self.assertIsNone(self.session_value('team_id'))

        html = self.client.get('/player/onboarding').get_data(as_text=True)
        self.assertIn('Čeká na schválení trenérem', html)
        self.assertIn('Alice Nováková', html)

    def test_pending_screen_tells_the_player_they_may_close_it(self):
        self.start_claim()
        html = self.client.get('/player/onboarding').get_data(as_text=True)
        self.assertIn('Nemusíš tuto stránku nechávat otevřenou', html)

    def test_brand_new_browser_with_only_the_cookie_resumes(self):
        token = self.start_claim()
        fresh = self.returning_browser(token)
        html = fresh.get('/player/onboarding').get_data(as_text=True)
        self.assertIn('Čeká na schválení trenérem', html)

    def test_approved_claim_is_recovered_without_the_player_key(self):
        token = self.start_claim()
        self.approve_latest()
        fresh = self.returning_browser(token)
        html = fresh.get('/player/onboarding').get_data(as_text=True)
        self.assertIn('Trenér přístup schválil', html)
        self.assertIn('Vytvořit passkey', html)
        self.assertIn('data-pk-register', html)

    def test_opening_the_site_root_offers_the_claim(self):
        token = self.start_claim()
        self.approve_latest()
        fresh = self.returning_browser(token)
        r = fresh.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/player/onboarding', r.headers['Location'])

    def test_root_is_normal_without_a_claim(self):
        self.assertEqual(app.test_client().get('/').status_code, 200)

    def test_resume_screen_does_not_expose_the_roster(self):
        """The cookie owns one request; it is not the shared player key."""
        token = self.start_claim()
        fresh = self.returning_browser(token)
        html = fresh.get('/player/onboarding').get_data(as_text=True)
        self.assertNotIn('Bob Svoboda', html)     # another roster member
        self.assertNotIn('Kdo jsi?', html)
        self.assertNotIn('To jsem já', html)


# =========================================================================
class ResumeIsNotAuthenticationTest(ResumeBase):
    """§8 — the whole point: possession continues one claim, nothing more."""

    APP_PATHS = ('/app', '/attendance', '/dochazka', '/players', '/roster',
                 '/lines', '/drills', '/nastenka', '/settings',
                 '/team/player-access')

    def test_resume_cookie_alone_cannot_reach_the_app(self):
        token = self.start_claim()
        self.approve_latest()
        fresh = self.returning_browser(token)
        for path in self.APP_PATHS:
            r = fresh.get(path)
            self.assertEqual(r.status_code, 302, path)
            self.assertIn('/team/auth', r.headers.get('Location', ''), path)

    def test_resume_cookie_cannot_mutate_attendance(self):
        token = self.start_claim()
        self.approve_latest()
        fresh = self.returning_browser(token)
        r = fresh.post('/attendance/cell', json={
            'player_id': self.alice_id, 'event_key': self.ev_key, 'status': 'going'})
        self.assertNotEqual(r.status_code, 200)
        self.assertEqual(db.session.query(
            db.func.count()).select_from(__import__(
                'coach.models', fromlist=['AttendanceEntry']).AttendanceEntry).scalar(), 0)

    def test_resume_cookie_does_not_create_a_session_identity(self):
        token = self.start_claim()
        self.approve_latest()
        fresh = self.returning_browser(token)
        fresh.get('/player/onboarding')
        with fresh.session_transaction() as s:
            self.assertIsNone(s.get('player_id'))
            self.assertIsNone(s.get('team_id'))
            self.assertIsNone(s.get('team_login'))

    def test_resume_cookie_cannot_claim_a_different_player(self):
        """Creating a claim still needs the shared player key."""
        token = self.start_claim()
        fresh = self.returning_browser(token)
        r = fresh.post('/player/onboarding/claim', data={'player_id': self.bob_id})
        self.assertEqual(r.status_code, 302)
        self.assertIn('/team/auth', r.headers.get('Location', ''))
        self.assertEqual(PlayerRegistrationRequest.query
                         .filter_by(player_id=self.bob_id).count(), 0)


# =========================================================================
class BrowserBindingTest(ResumeBase):
    """§17 — the claim belongs to one browser, not to the player key."""

    def test_another_browser_with_the_player_key_cannot_finish_it(self):
        self.start_claim()
        self.approve_latest()

        other = app.test_client()                 # knows the shared key, no cookie
        self.key_login(self.tid, 'player', PLAYER_KEY_A, other)
        r = other.post('/passkey/register/options')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()['error'], 'not_found')
        self.assertEqual(PasskeyCredential.query.count(), 0)

    def test_another_browser_may_start_its_own_request(self):
        self.start_claim()
        other = app.test_client()
        self.key_login(self.tid, 'player', PLAYER_KEY_A, other)
        other.post('/player/onboarding/claim', data={'player_id': self.bob_id})
        self.assertEqual(PlayerRegistrationRequest.query
                         .filter_by(player_id=self.bob_id,
                                    status=PlayerRegistrationRequest.STATUS_PENDING)
                         .count(), 1)

    def test_a_guessed_token_resolves_to_nothing(self):
        self.start_claim()
        for guess in ('', 'x', 'a' * 43, ident.new_claim_token()):
            self.assertIsNone(ident.find_by_token(guess))


# =========================================================================
class TerminalStatesInvalidateTheTokenTest(ResumeBase):
    """§12-§15 — activation, rejection, expiry, cancellation all dead-end."""

    def _assert_cookie_cleared(self, resp):
        header = self._onboarding_cookie_header(resp)
        self.assertIsNotNone(header, 'expected the cookie to be deleted')
        self.assertTrue('Max-Age=0' in header or 'Expires=Thu, 01 Jan 1970' in header,
                        'cookie was not expired: %s' % header)

    def test_activation_invalidates_the_token_and_removes_the_cookie(self):
        token = self.start_claim()
        self.approve_latest()
        auth, resp = self.register_passkey()
        self.assertEqual(resp.status_code, 200)
        self._assert_cookie_cleared(resp)

        req = self.latest_request(self.alice_id)
        self.assertEqual(req.status, PlayerRegistrationRequest.STATUS_ACTIVATED)
        # replay with the very same token must not mint a second credential
        replay = self.returning_browser(token)
        r = replay.post('/passkey/register/options')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()['error'], 'not_approved')
        self.assertEqual(PasskeyCredential.query.count(), 1)

    def test_rejected_request_cannot_register_and_clears_the_cookie(self):
        token = self.start_claim()
        req = self.latest_request(self.alice_id)
        coach = app.test_client()
        self.login_coach(client=coach)
        coach.post('/team/player-access/%d/reject' % req.id)

        fresh = self.returning_browser(token)
        r = fresh.post('/passkey/register/options')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(PasskeyCredential.query.count(), 0)
        # returning to the page bounces to login and drops the dead cookie
        page = fresh.get('/player/onboarding')
        self.assertEqual(page.status_code, 302)
        self._assert_cookie_cleared(page)

    def test_expired_request_cannot_be_resumed(self):
        token = self.start_claim()
        self.approve_latest()
        req = self.latest_request(self.alice_id)
        req.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.session.commit()

        fresh = self.returning_browser(token)
        r = fresh.post('/passkey/register/options')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()['error'], 'expired')
        page = fresh.get('/player/onboarding')
        self.assertEqual(page.status_code, 302)
        self._assert_cookie_cleared(page)
        self.assertEqual(PasskeyCredential.query.count(), 0)

    def test_cancel_invalidates_the_token_and_clears_the_cookie(self):
        token = self.start_claim()
        self.drop_session_keep_cookie()
        resp = self.client.post('/player/onboarding/cancel')
        self._assert_cookie_cleared(resp)

        req = self.latest_request(self.alice_id)
        self.assertEqual(req.status, PlayerRegistrationRequest.STATUS_REJECTED)
        replay = self.returning_browser(token)
        self.assertEqual(replay.post('/passkey/register/options').status_code, 403)

    def test_explicit_logout_forgets_the_browser(self):
        """§16 — closing the app keeps the claim; logging out deliberately does not."""
        self.start_claim()
        resp = self.client.get('/team/logout')
        self._assert_cookie_cleared(resp)


# =========================================================================
class ForgedIdentityTest(ResumeBase):
    """§19/§23 — client-supplied ids must never steer the activation."""

    def test_activation_binds_to_the_request_not_to_posted_fields(self):
        token = self.start_claim(self.alice_id)
        req = self.approve_latest(self.alice_id)
        fresh = self.returning_browser(token)

        # every id the client could try to bend, sent alongside the ceremony
        r = fresh.post('/passkey/register/options',
                       data={'player_id': self.bob_id, 'team_id': self.other_tid,
                             'request_id': 9999})
        self.assertEqual(r.status_code, 200)
        options = r.get_json()['options']

        from coach.tests.webauthn_fake import SoftAuthenticator
        auth = SoftAuthenticator()
        attestation = auth.create(options, origin='http://localhost', rp_id='localhost')
        r = fresh.post('/passkey/register/verify',
                       json={'credential': attestation, 'player_id': self.bob_id,
                             'team_id': self.other_tid, 'request_id': 9999})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

        cred = PasskeyCredential.query.one()
        self.assertEqual(cred.player_id, self.alice_id)   # NOT bob
        self.assertEqual(cred.team_id, self.tid)          # NOT the other team
        self.assertEqual(cred.role, 'player')
        with fresh.session_transaction() as s:
            self.assertEqual(s['player_id'], self.alice_id)

    def test_approval_is_still_required_before_any_credential(self):
        token = self.start_claim()
        fresh = self.returning_browser(token)        # pending, never approved
        r = fresh.post('/passkey/register/options')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()['error'], 'not_approved')
        self.assertEqual(PasskeyCredential.query.count(), 0)


# =========================================================================
class SupersedingClaimsTest(ResumeBase):
    """§18 — one resumable claim per browser, deterministically."""

    def test_new_claim_supersedes_the_previous_one_and_rotates_the_token(self):
        first = self.start_claim(self.alice_id)
        self.claim(self.bob_id)
        second = self.resume_cookie()
        self.assertNotEqual(first, second)

        old = ident.find_by_token(first)
        self.assertEqual(old.player_id, self.alice_id)
        self.assertEqual(old.status, PlayerRegistrationRequest.STATUS_REJECTED)
        new = ident.find_by_token(second)
        self.assertEqual(new.player_id, self.bob_id)
        self.assertEqual(new.status, PlayerRegistrationRequest.STATUS_PENDING)

    def test_the_superseded_token_can_no_longer_resume(self):
        first = self.start_claim(self.alice_id)
        self.claim(self.bob_id)
        stale = self.returning_browser(first)
        self.assertEqual(stale.get('/player/onboarding').status_code, 302)

    def test_each_token_maps_to_exactly_one_request(self):
        self.start_claim(self.alice_id)
        self.claim(self.bob_id)
        hashes = [r.claim_token_hash for r in PlayerRegistrationRequest.query.all()]
        self.assertEqual(len(hashes), len(set(hashes)))


# =========================================================================
class PasskeyLoginUnaffectedTest(ResumeBase):
    """§22 — the finished flow must keep working, stale cookie or not."""

    def test_login_still_works_after_activation(self):
        auth = self.onboard_fully(self.alice_id)
        fresh = app.test_client()
        r = self.login_passkey(auth, client=fresh)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()['ok'])
        with fresh.session_transaction() as s:
            self.assertEqual(s['player_id'], self.alice_id)

    def test_a_stale_resume_cookie_does_not_block_passkey_login(self):
        token = self.start_claim()
        auth = self.onboard_fully(self.alice_id)
        stale = self.returning_browser(token)     # activated token, still held
        r = self.login_passkey(auth, client=stale)
        self.assertEqual(r.status_code, 200)
        with stale.session_transaction() as s:
            self.assertEqual(s['player_id'], self.alice_id)


# =========================================================================
class NoSchemaChangeTest(unittest.TestCase):
    """§27 — the feature reuses the existing claim token columns."""

    def test_reuses_existing_columns_only(self):
        cols = {c.name for c in PlayerRegistrationRequest.__table__.columns}
        for needed in ('claim_token_hash', 'expires_at', 'status',
                       'team_id', 'player_id'):
            self.assertIn(needed, cols)
        # nothing resume-specific was bolted on
        self.assertFalse([c for c in cols if 'resume' in c or 'cookie' in c])


if __name__ == '__main__':
    unittest.main()
