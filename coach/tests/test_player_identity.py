# -*- coding: utf-8 -*-
"""Player identity model: onboarding claim -> coach approval -> passkey.

Covers the security property the whole design exists for:

    holding the shared player key must NEVER be enough to act as a player.

The WebAuthn ceremonies are exercised for real against py_webauthn using a
software authenticator (`webauthn_fake`), so challenge, origin, RP ID hash,
signature and sign-counter checks all genuinely run. Nothing in the server's
verification path is stubbed.
"""
import json
import unittest
from datetime import date, datetime, timedelta

from coach.app import app
from coach.extensions import db
from coach.models import (AttendanceEntry, PasskeyCredential, Player,
                          PlayerRegistrationRequest, Team, TeamKey, TrainingEvent)
from coach.services import player_identity as ident
from coach.services.keys import hash_team_key
from coach.tests.webauthn_fake import SoftAuthenticator

ORIGIN = 'http://localhost'
RP_ID = 'localhost'

COACH_KEY_A, PLAYER_KEY_A = 'coach-key-alpha', 'player-key-alpha'
COACH_KEY_B, PLAYER_KEY_B = 'coach-key-beta', 'player-key-beta'


class IdentityTestBase(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
                          ADMIN_SECRET_KEY='owner-secret',
                          WEBAUTHN_RP_ID='', WEBAUTHN_ORIGIN='')
        # These tests log in far more often than a human would; the real
        # per-minute limits are covered by test_rate_limits.py.
        from coach.extensions import limiter
        self._limiter = limiter
        self._limiter_was_enabled = limiter.enabled
        limiter.enabled = False
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()

        self.team = Team(name='Alpha HC')
        self.other_team = Team(name='Beta HC')
        db.session.add_all([self.team, self.other_team])
        db.session.flush()
        self.tid, self.other_tid = self.team.id, self.other_team.id
        db.session.add_all([
            TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key(COACH_KEY_A)),
            TeamKey(team_id=self.tid, role='player', key_hash=hash_team_key(PLAYER_KEY_A)),
            TeamKey(team_id=self.other_tid, role='coach', key_hash=hash_team_key(COACH_KEY_B)),
            TeamKey(team_id=self.other_tid, role='player', key_hash=hash_team_key(PLAYER_KEY_B)),
        ])
        self.alice = Player(team_id=self.tid, name='Alice Nováková', position='F')
        self.bob = Player(team_id=self.tid, name='Bob Svoboda', position='D')
        self.foreign = Player(team_id=self.other_tid, name='Beta Hráč', position='G')
        db.session.add_all([self.alice, self.bob, self.foreign])

        ev = TrainingEvent(team_id=self.tid, day=date.today() + timedelta(days=2),
                           time='18:00', title='Trénink', kind='training')
        ev_other = TrainingEvent(team_id=self.other_tid, day=date.today() + timedelta(days=2),
                                 time='19:00', title='Trénink B', kind='training')
        db.session.add_all([ev, ev_other])
        db.session.commit()
        self.alice_id, self.bob_id, self.foreign_id = self.alice.id, self.bob.id, self.foreign.id
        self.ev_key = 'local:%d' % ev.id
        self.ev_key_other = 'local:%d' % ev_other.id
        self.client = app.test_client()

    def tearDown(self):
        self._limiter.enabled = self._limiter_was_enabled
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    # ------------------------------------------------------------ helpers
    def key_login(self, team_id, role, key, client=None):
        """Log in through the REAL shared-key route."""
        c = client or self.client
        return c.post('/team/login', data={'team_id': team_id, 'role': role,
                                           'key': key, 'terms_accept': 'on'})

    def login_player_key(self, client=None):
        return self.key_login(self.tid, 'player', PLAYER_KEY_A, client)

    def login_coach(self, team_id=None, key=None, client=None):
        return self.key_login(team_id or self.tid, 'coach', key or COACH_KEY_A, client)

    def login_verified(self, player_id, team_id=None, client=None):
        """Shortcut for an already-passkey-verified session."""
        c = client or self.client
        with c.session_transaction() as s:
            s['team_id'] = team_id or self.tid
            s['team_role'] = 'player'
            s['team_login'] = True
            s['auth_method'] = 'passkey'
            s['player_id'] = player_id

    def claim(self, player_id, client=None):
        c = client or self.client
        return c.post('/player/onboarding/claim', data={'player_id': player_id})

    def latest_request(self, player_id=None):
        q = PlayerRegistrationRequest.query
        if player_id:
            q = q.filter_by(player_id=player_id)
        return q.order_by(PlayerRegistrationRequest.id.desc()).first()

    def session_value(self, key, client=None):
        c = client or self.client
        with c.session_transaction() as s:
            return s.get(key)

    def resume_cookie(self, client=None):
        """Raw onboarding resume token this browser is holding, or None."""
        c = client or self.client
        return c.get_cookie('chh_onboarding', domain='localhost') and \
            c.get_cookie('chh_onboarding', domain='localhost').value

    def drop_session_keep_cookie(self, client=None):
        """Simulate closing the browser: the Flask session is gone, the
        persistent resume cookie survives."""
        c = client or self.client
        c.delete_cookie('session', domain='localhost')
        with c.session_transaction() as s:
            s.clear()

    # -- full ceremonies ---------------------------------------------------
    def register_passkey(self, client=None, authenticator=None, origin=ORIGIN):
        """Drive /passkey/register/{options,verify} with a software authenticator."""
        c = client or self.client
        auth = authenticator or SoftAuthenticator()
        r = c.post('/passkey/register/options')
        if r.status_code != 200:
            return auth, r
        options = r.get_json()['options']
        attestation = auth.create(options, origin=origin, rp_id=RP_ID)
        return auth, c.post('/passkey/register/verify',
                            json={'credential': attestation})

    def login_passkey(self, auth, client=None, origin=ORIGIN, **kwargs):
        """Drive /passkey/login/{options,verify}."""
        c = client or self.client
        r = c.post('/passkey/login/options')
        self.assertEqual(r.status_code, 200)
        options = r.get_json()['options']
        assertion = auth.get(options, origin=origin, rp_id=RP_ID, **kwargs)
        return c.post('/passkey/login/verify', json={'credential': assertion})

    def onboard_fully(self, player_id, client=None):
        """player key -> claim -> coach approves -> passkey. Returns authenticator."""
        c = client or self.client
        self.login_player_key(c)
        self.claim(player_id, c)
        req = self.latest_request(player_id)
        coach = app.test_client()
        self.login_coach(client=coach)
        coach.post('/team/player-access/%d/approve' % req.id)
        auth, resp = self.register_passkey(c)
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        return auth


# =========================================================================
class OnboardingTest(IdentityTestBase):
    """§23 — registration flow."""

    def test_valid_player_key_can_start_onboarding(self):
        self.login_player_key()
        r = self.client.get('/player/onboarding')
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn('Alice Nováková', html)
        self.assertIn('Bob Svoboda', html)

    def test_invalid_player_key_cannot(self):
        self.key_login(self.tid, 'player', 'totally-wrong-key')
        self.assertIsNone(self.session_value('team_id'))
        r = self.client.get('/player/onboarding')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/team/auth', r.headers.get('Location', ''))

    def test_player_key_scopes_the_team_only(self):
        """The key must yield team scope and NOTHING resembling a player id."""
        self.login_player_key()
        self.assertEqual(self.session_value('team_id'), self.tid)
        self.assertEqual(self.session_value('team_role'), 'player')
        self.assertEqual(self.session_value('auth_method'), 'team_key')
        self.assertIsNone(self.session_value('player_id'))

    def test_selection_creates_pending_request_with_temporary_name(self):
        self.login_player_key()
        r = self.claim(self.alice_id)
        self.assertEqual(r.status_code, 302)
        req = self.latest_request()
        self.assertIsNotNone(req)
        self.assertEqual(req.player_id, self.alice_id)
        self.assertEqual(req.team_id, self.tid)
        self.assertEqual(req.status, 'pending')
        self.assertEqual(req.claimed_name, 'Alice Nováková')
        self.assertGreater(req.expires_at, datetime.utcnow())

    def test_selection_does_not_authenticate_as_that_player(self):
        """The heart of the model: picking a name grants nothing."""
        self.login_player_key()
        self.claim(self.alice_id)
        self.assertIsNone(self.session_value('player_id'))
        self.assertEqual(self.session_value('auth_method'), 'team_key')

    def test_selecting_another_teams_player_is_refused(self):
        self.login_player_key()
        self.claim(self.foreign_id)
        self.assertEqual(PlayerRegistrationRequest.query.count(), 0)

    def test_coach_sees_pending_request(self):
        self.login_player_key()
        self.claim(self.alice_id)
        coach = app.test_client()
        self.login_coach(client=coach)
        html = coach.get('/team/player-access').get_data(as_text=True)
        self.assertIn('Alice Nováková', html)

    def test_coach_of_correct_team_can_approve(self):
        self.login_player_key()
        self.claim(self.alice_id)
        req_id = self.latest_request().id
        coach = app.test_client()
        self.login_coach(client=coach)
        r = coach.post('/team/player-access/%d/approve' % req_id)
        self.assertEqual(r.status_code, 302)
        db.session.expire_all()
        req = db.session.get(PlayerRegistrationRequest, req_id)
        self.assertEqual(req.status, 'approved')
        self.assertIsNotNone(req.approved_at)

    def test_coach_from_another_team_cannot_approve(self):
        """A forged request id must not cross the team boundary."""
        self.login_player_key()
        self.claim(self.alice_id)
        req_id = self.latest_request().id
        intruder = app.test_client()
        self.login_coach(team_id=self.other_tid, key=COACH_KEY_B, client=intruder)
        r = intruder.post('/team/player-access/%d/approve' % req_id)
        self.assertEqual(r.status_code, 302)
        db.session.expire_all()
        self.assertEqual(db.session.get(PlayerRegistrationRequest, req_id).status, 'pending')

    def test_coach_from_another_team_cannot_reject(self):
        self.login_player_key()
        self.claim(self.alice_id)
        req_id = self.latest_request().id
        intruder = app.test_client()
        self.login_coach(team_id=self.other_tid, key=COACH_KEY_B, client=intruder)
        intruder.post('/team/player-access/%d/reject' % req_id)
        db.session.expire_all()
        req = db.session.get(PlayerRegistrationRequest, req_id)
        self.assertEqual(req.status, 'pending')
        self.assertEqual(req.claimed_name, 'Alice Nováková')

    def test_player_role_cannot_approve_its_own_request(self):
        self.login_player_key()
        self.claim(self.alice_id)
        req_id = self.latest_request().id
        r = self.client.post('/team/player-access/%d/approve' % req_id)
        self.assertEqual(r.status_code, 302)
        db.session.expire_all()
        self.assertEqual(db.session.get(PlayerRegistrationRequest, req_id).status, 'pending')

    def test_coach_can_reject_and_name_is_wiped(self):
        self.login_player_key()
        self.claim(self.alice_id)
        req_id = self.latest_request().id
        coach = app.test_client()
        self.login_coach(client=coach)
        coach.post('/team/player-access/%d/reject' % req_id)
        db.session.expire_all()
        req = db.session.get(PlayerRegistrationRequest, req_id)
        self.assertEqual(req.status, 'rejected')
        self.assertIsNone(req.claimed_name)
        self.assertIsNotNone(req.rejected_at)

    def test_expired_request_cannot_be_approved(self):
        self.login_player_key()
        self.claim(self.alice_id)
        req = self.latest_request()
        req.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.session.commit()
        coach = app.test_client()
        self.login_coach(client=coach)
        coach.post('/team/player-access/%d/approve' % req.id)
        db.session.expire_all()
        self.assertEqual(db.session.get(PlayerRegistrationRequest, req.id).status, 'pending')

    def test_expired_request_is_not_listed_for_the_coach(self):
        self.login_player_key()
        self.claim(self.alice_id)
        req = self.latest_request()
        req.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.session.commit()
        coach = app.test_client()
        self.login_coach(client=coach)
        html = coach.get('/team/player-access').get_data(as_text=True)
        self.assertIn('Žádné čekající žádosti', html)

    def test_rejected_request_cannot_become_active(self):
        self.login_player_key()
        self.claim(self.alice_id)
        req_id = self.latest_request().id
        coach = app.test_client()
        self.login_coach(client=coach)
        coach.post('/team/player-access/%d/reject' % req_id)
        r = self.client.post('/passkey/register/options')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()['error'], 'not_approved')
        self.assertEqual(PasskeyCredential.query.count(), 0)

    def test_pending_request_cannot_create_a_passkey(self):
        self.login_player_key()
        self.claim(self.alice_id)
        r = self.client.post('/passkey/register/options')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()['error'], 'not_approved')

    def test_expired_approval_cannot_create_a_passkey(self):
        self.login_player_key()
        self.claim(self.alice_id)
        req = self.latest_request()
        coach = app.test_client()
        self.login_coach(client=coach)
        coach.post('/team/player-access/%d/approve' % req.id)
        db.session.expire_all()
        req = self.latest_request()
        req.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.session.commit()
        r = self.client.post('/passkey/register/options')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()['error'], 'expired')

    def test_new_claim_supersedes_this_browsers_previous_pending_one(self):
        self.login_player_key()
        self.claim(self.alice_id)
        self.claim(self.bob_id)
        rows = PlayerRegistrationRequest.query.order_by(PlayerRegistrationRequest.id).all()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].status, 'rejected')     # superseded
        self.assertIsNone(rows[0].claimed_name)
        self.assertEqual(rows[1].status, 'pending')
        self.assertEqual(rows[1].player_id, self.bob_id)

    def test_player_can_cancel_own_request(self):
        self.login_player_key()
        self.claim(self.alice_id)
        req_id = self.latest_request().id
        self.client.post('/player/onboarding/cancel')
        db.session.expire_all()
        self.assertEqual(db.session.get(PlayerRegistrationRequest, req_id).status, 'rejected')


# =========================================================================
class SharedKeyGateTest(IdentityTestBase):
    """Reproduces the reported bug: coach adds a player, logs out, player key
    login dropped straight into the app instead of the onboarding screen.

    Two independent defects were behind it — the post-login redirect AND the
    absence of any global gate — so both are pinned here.
    """

    def test_player_key_login_redirects_to_onboarding(self):
        """The exact reported sequence: add a player as coach, then key-login."""
        coach = app.test_client()
        self.login_coach(client=coach)
        coach.post('/add_player', data={'name': 'Martin Šnajdr', 'position': 'F'})
        self.assertIsNotNone(Player.query.filter_by(name='Martin Šnajdr').first())
        coach.get('/team/logout')

        r = self.login_player_key()
        self.assertEqual(r.status_code, 302)
        self.assertIn('/player/onboarding', r.headers.get('Location', ''),
                      'player key login must land on onboarding, not the app')
        self.assertEqual(self.session_value('auth_method'), 'team_key')
        self.assertIsNone(self.session_value('player_id'))

    def test_player_key_login_does_not_land_on_app(self):
        r = self.client.post('/team/login',
                             data={'team_id': self.tid, 'role': 'player',
                                   'key': PLAYER_KEY_A, 'terms_accept': 'on'},
                             follow_redirects=True)
        html = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn('Ověření hráče', html)          # the onboarding screen
        self.assertIn('Kdo jsi?', html)

    def test_typing_a_url_cannot_bypass_onboarding(self):
        """§12 — hiding nav is not the fix; the backend must refuse."""
        self.login_player_key()
        for path in ('/app', '/attendance', '/players', '/roster', '/lines',
                     '/dochazka', '/drills', '/nastenka', '/pokladna', '/settings',
                     '/attendance/import', '/team/keys', '/team/player-access'):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 302, path)
            self.assertIn('/player/onboarding', r.headers.get('Location', ''), path)

    def test_onboarding_paths_stay_reachable_no_redirect_loop(self):
        self.login_player_key()
        r = self.client.get('/player/onboarding')
        self.assertEqual(r.status_code, 200)
        # logout must remain available from the onboarding dead-end
        self.assertEqual(self.client.get('/team/logout').status_code, 302)

    def test_pending_claim_still_cannot_reach_the_app(self):
        self.login_player_key()
        self.claim(self.alice_id)
        r = self.client.get('/app')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/player/onboarding', r.headers.get('Location', ''))
        html = self.client.get('/player/onboarding').get_data(as_text=True)
        self.assertIn('Čeká na schválení', html)
        self.assertIn('Alice Nováková', html)

    def test_approved_but_no_passkey_still_cannot_reach_the_app(self):
        """§7 — approval alone must not turn the shared key into the identity."""
        self.login_player_key()
        self.claim(self.alice_id)
        req = self.latest_request()
        coach = app.test_client()
        self.login_coach(client=coach)
        coach.post('/team/player-access/%d/approve' % req.id)

        r = self.client.get('/app')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/player/onboarding', r.headers.get('Location', ''))
        self.assertIsNone(self.session_value('player_id'))
        html = self.client.get('/player/onboarding').get_data(as_text=True)
        self.assertIn('Vytvořit passkey', html)

    def test_verified_player_is_not_redirected_to_onboarding(self):
        """§8 — the gate must not bounce the people it is meant to admit."""
        auth = self.onboard_fully(self.alice_id)
        fresh = app.test_client()
        self.login_passkey(auth, client=fresh)
        for path in ('/app', '/attendance', '/players', '/drills', '/nastenka'):
            self.assertEqual(fresh.get(path).status_code, 200, path)

    def test_coach_login_is_unchanged(self):
        """§9 — coaches go to the app, never to onboarding."""
        r = self.login_coach()
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('/player/onboarding', r.headers.get('Location', ''))
        self.assertIn('/app', r.headers.get('Location', ''))
        for path in ('/app', '/players', '/dochazka', '/settings', '/attendance/import'):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_legacy_session_without_auth_method_is_treated_as_shared_key(self):
        """Sessions predating auth_method must not be grandfathered into the app."""
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid
            s['team_role'] = 'player'
            s['team_login'] = True          # no auth_method, no player_id
        r = self.client.get('/app')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/player/onboarding', r.headers.get('Location', ''))

    def test_forged_auth_method_without_player_id_is_not_enough(self):
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid
            s['team_role'] = 'player'
            s['team_login'] = True
            s['auth_method'] = 'passkey'     # claimed, but no player_id
        r = self.client.get('/app')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/player/onboarding', r.headers.get('Location', ''))

    def test_onboarding_lists_only_this_teams_players(self):
        self.login_player_key()
        html = self.client.get('/player/onboarding').get_data(as_text=True)
        self.assertIn('Alice Nováková', html)
        self.assertIn('Bob Svoboda', html)
        self.assertNotIn('Beta Hráč', html)          # other team's roster

    def test_empty_roster_shows_a_message_and_keeps_logout(self):
        """§5 — no players must not crash or fall through into the app."""
        Player.query.filter_by(team_id=self.tid).delete()
        db.session.commit()
        self.login_player_key()
        r = self.client.get('/player/onboarding')
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn('Zatím tu nejsou žádní hráči k registraci', html)
        self.assertIn(url_for_logout(), html)
        self.assertEqual(self.client.get('/app').status_code, 302)

    def test_shared_key_nav_offers_no_app_links(self):
        """UI matches the gate — no links that would only bounce back."""
        self.login_player_key()
        html = self.client.get('/player/onboarding').get_data(as_text=True)
        self.assertIn('nav-disabled', html)          # inert nav variant
        self.assertNotIn('id="mnavDochazka"', html)  # mobile bottom nav withheld
        self.assertIn(url_for_logout(), html)        # but logout stays


def url_for_logout():
    with app.test_request_context():
        from flask import url_for
        return url_for('team_logout')


# =========================================================================
class ClaimBindingTest(IdentityTestBase):
    """§24 — a claim belongs to the browser that made it."""

    def test_another_browser_cannot_complete_an_approved_claim(self):
        """Holding the shared player key must not let someone else finish an
        approved registration and mint a passkey for that identity."""
        self.login_player_key()
        self.claim(self.alice_id)
        req = self.latest_request()
        coach = app.test_client()
        self.login_coach(client=coach)
        coach.post('/team/player-access/%d/approve' % req.id)

        attacker = app.test_client()                 # same shared key, other browser
        self.login_player_key(attacker)
        r = attacker.post('/passkey/register/options')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()['error'], 'not_found')
        self.assertEqual(PasskeyCredential.query.count(), 0)

    def test_claim_from_another_team_is_invisible(self):
        """A session on team B must not resolve team A's request, even holding
        the same token. (The token now lives in the resume cookie rather than
        the session, but the team-scoped lookup is unchanged.)"""
        self.login_player_key()
        self.claim(self.alice_id)
        token = self.resume_cookie()
        self.assertIsNotNone(token)
        self.assertIsNone(ident.find_by_claim_token(self.other_tid, token))
        self.assertIsNotNone(ident.find_by_claim_token(self.tid, token))

    def test_other_teams_session_holding_the_cookie_sees_no_claim(self):
        """View-level form of the same property: team B's onboarding page must
        not surface team A's pending claim just because the cookie is present."""
        self.login_player_key()
        self.claim(self.alice_id)
        token = self.resume_cookie()

        crossover = app.test_client()
        crossover.set_cookie('chh_onboarding', token, domain='localhost')
        self.key_login(self.other_tid, 'player', PLAYER_KEY_B, crossover)
        html = crossover.get('/player/onboarding').get_data(as_text=True)
        self.assertNotIn('Čeká na schválení trenérem', html)
        self.assertIn('Kdo jsi?', html)          # ...it just offers its own roster


# =========================================================================
class PasskeyLifecycleTest(IdentityTestBase):
    """§26 — credential lifecycle, verified against real WebAuthn responses."""

    def test_full_flow_binds_credential_to_the_correct_player(self):
        auth = self.onboard_fully(self.alice_id)
        cred = PasskeyCredential.query.one()
        self.assertEqual(cred.player_id, self.alice_id)
        self.assertEqual(cred.team_id, self.tid)
        self.assertEqual(cred.role, 'player')
        self.assertEqual(cred.status, 'active')
        self.assertTrue(cred.public_key)
        self.assertTrue(cred.credential_id)
        # Session became an individually authenticated player.
        self.assertEqual(self.session_value('player_id'), self.alice_id)
        self.assertEqual(self.session_value('auth_method'), 'passkey')
        self.assertIsNotNone(auth)

    def test_user_handle_is_opaque(self):
        """No name, no numeric player id, nothing readable."""
        self.onboard_fully(self.alice_id)
        cred = PasskeyCredential.query.one()
        self.assertGreaterEqual(len(cred.user_handle), 40)
        self.assertNotIn('Alice', cred.user_handle)
        self.assertNotIn('Nováková', cred.user_handle)
        self.assertNotEqual(cred.user_handle, str(self.alice_id))
        self.assertNotIn(str(self.alice_id), cred.user_handle[:4])

    def test_active_credential_authenticates(self):
        auth = self.onboard_fully(self.alice_id)
        fresh = app.test_client()
        r = self.login_passkey(auth, client=fresh)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()['ok'])
        with fresh.session_transaction() as s:
            self.assertEqual(s['player_id'], self.alice_id)
            self.assertEqual(s['team_id'], self.tid)
            self.assertEqual(s['team_role'], 'player')
            self.assertEqual(s['auth_method'], 'passkey')

    def test_login_needs_no_shared_key(self):
        """A returning player signs in with the passkey alone."""
        auth = self.onboard_fully(self.alice_id)
        fresh = app.test_client()                    # never saw a team key
        self.assertEqual(self.login_passkey(auth, client=fresh).status_code, 200)

    def test_pending_credential_cannot_authenticate(self):
        auth = self.onboard_fully(self.alice_id)
        cred = PasskeyCredential.query.one()
        cred.status = PasskeyCredential.STATUS_PENDING
        db.session.commit()
        fresh = app.test_client()
        r = self.login_passkey(auth, client=fresh)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()['error'], 'unknown_credential')
        self.assertIsNone(self.session_value('player_id', fresh))

    def test_revoked_credential_cannot_authenticate(self):
        auth = self.onboard_fully(self.alice_id)
        coach = app.test_client()
        self.login_coach(client=coach)
        coach.post('/team/player-access/player/%d/revoke' % self.alice_id)
        db.session.expire_all()
        self.assertEqual(PasskeyCredential.query.one().status, 'revoked')
        self.assertIsNotNone(PasskeyCredential.query.one().revoked_at)
        fresh = app.test_client()
        r = self.login_passkey(auth, client=fresh)
        self.assertEqual(r.status_code, 403)
        self.assertIsNone(self.session_value('player_id', fresh))

    def test_unknown_credential_fails(self):
        self.onboard_fully(self.alice_id)
        stranger = SoftAuthenticator()               # never registered
        fresh = app.test_client()
        r = self.login_passkey(stranger, client=fresh)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()['error'], 'unknown_credential')

    def test_tampered_signature_fails(self):
        auth = self.onboard_fully(self.alice_id)
        fresh = app.test_client()
        r = self.login_passkey(auth, client=fresh, tamper_signature=True)
        self.assertEqual(r.status_code, 403)
        self.assertIsNone(self.session_value('player_id', fresh))

    def test_wrong_origin_fails(self):
        auth = self.onboard_fully(self.alice_id)
        fresh = app.test_client()
        r = self.login_passkey(auth, client=fresh, origin='https://evil.example')
        self.assertEqual(r.status_code, 403)
        self.assertIsNone(self.session_value('player_id', fresh))

    def test_replayed_sign_counter_fails(self):
        """A cloned authenticator replaying an old counter is rejected."""
        auth = self.onboard_fully(self.alice_id)
        fresh = app.test_client()
        self.assertEqual(self.login_passkey(auth, client=fresh, sign_count=5).status_code, 200)
        db.session.expire_all()
        self.assertEqual(PasskeyCredential.query.one().sign_count, 5)
        replay = app.test_client()
        r = self.login_passkey(auth, client=replay, sign_count=3)
        self.assertEqual(r.status_code, 403)
        self.assertIsNone(self.session_value('player_id', replay))

    def test_challenge_is_single_use(self):
        """Replaying a whole assertion against a burnt challenge fails."""
        auth = self.onboard_fully(self.alice_id)
        fresh = app.test_client()
        options = fresh.post('/passkey/login/options').get_json()['options']
        assertion = auth.get(options, origin=ORIGIN, rp_id=RP_ID)
        self.assertEqual(fresh.post('/passkey/login/verify',
                                    json={'credential': assertion}).status_code, 200)
        replay = fresh.post('/passkey/login/verify', json={'credential': assertion})
        self.assertEqual(replay.status_code, 403)

    def test_credential_from_other_team_gets_only_its_own_team(self):
        """A team B passkey authenticates into team B — never escalates into A."""
        other_client = app.test_client()
        other_client.post('/team/login', data={'team_id': self.other_tid, 'role': 'player',
                                               'key': PLAYER_KEY_B, 'terms_accept': 'on'})
        other_client.post('/player/onboarding/claim', data={'player_id': self.foreign_id})
        req = self.latest_request(self.foreign_id)
        coach_b = app.test_client()
        self.login_coach(team_id=self.other_tid, key=COACH_KEY_B, client=coach_b)
        coach_b.post('/team/player-access/%d/approve' % req.id)
        auth, resp = self.register_passkey(other_client)
        self.assertEqual(resp.status_code, 200)

        fresh = app.test_client()
        self.assertEqual(self.login_passkey(auth, client=fresh).status_code, 200)
        with fresh.session_transaction() as s:
            self.assertEqual(s['team_id'], self.other_tid)
            self.assertEqual(s['player_id'], self.foreign_id)
            self.assertNotEqual(s['team_id'], self.tid)

    def test_second_device_needs_a_fresh_approval(self):
        """§12 — existing credentials are never overwritten."""
        first = self.onboard_fully(self.alice_id)
        second_browser = app.test_client()
        self.login_player_key(second_browser)
        self.claim(self.alice_id, second_browser)
        # Still gated: an existing active credential grants no shortcut.
        self.assertEqual(second_browser.post('/passkey/register/options').status_code, 403)
        req = self.latest_request(self.alice_id)
        coach = app.test_client()
        self.login_coach(client=coach)
        coach.post('/team/player-access/%d/approve' % req.id)
        second, resp = self.register_passkey(second_browser)
        self.assertEqual(resp.status_code, 200)

        creds = PasskeyCredential.query.filter_by(player_id=self.alice_id, status='active').all()
        self.assertEqual(len(creds), 2)
        # Same opaque user handle -> one WebAuthn user, two devices.
        self.assertEqual(creds[0].user_handle, creds[1].user_handle)
        # BOTH devices still work; nothing was overwritten.
        for a in (first, second):
            c = app.test_client()
            self.assertEqual(self.login_passkey(a, client=c).status_code, 200)

    def test_revoking_one_player_does_not_touch_another(self):
        alice_auth = self.onboard_fully(self.alice_id)
        bob_auth = self.onboard_fully(self.bob_id, client=app.test_client())
        coach = app.test_client()
        self.login_coach(client=coach)
        coach.post('/team/player-access/player/%d/revoke' % self.alice_id)
        self.assertEqual(self.login_passkey(alice_auth, client=app.test_client()).status_code, 403)
        self.assertEqual(self.login_passkey(bob_auth, client=app.test_client()).status_code, 200)

    def test_coach_from_another_team_cannot_revoke(self):
        auth = self.onboard_fully(self.alice_id)
        cred_id = PasskeyCredential.query.one().id
        intruder = app.test_client()
        self.login_coach(team_id=self.other_tid, key=COACH_KEY_B, client=intruder)
        intruder.post('/team/player-access/credential/%d/revoke' % cred_id)
        db.session.expire_all()
        self.assertEqual(db.session.get(PasskeyCredential, cred_id).status, 'active')
        self.assertEqual(self.login_passkey(auth, client=app.test_client()).status_code, 200)

    def test_deleting_the_player_removes_their_access(self):
        auth = self.onboard_fully(self.alice_id)
        coach = app.test_client()
        self.login_coach(client=coach)
        coach.post('/delete_player/%d' % self.alice_id)
        self.assertEqual(PasskeyCredential.query.filter_by(player_id=self.alice_id).count(), 0)
        self.assertEqual(self.login_passkey(auth, client=app.test_client()).status_code, 403)


# =========================================================================
class DataMinimizationTest(IdentityTestBase):
    """§7 / §29 — temporary identifying data is destroyed; logs stay opaque."""

    def test_claimed_name_is_deleted_after_activation(self):
        self.onboard_fully(self.alice_id)
        req = self.latest_request(self.alice_id)
        self.assertEqual(req.status, 'activated')
        self.assertIsNone(req.claimed_name)
        self.assertIsNotNone(req.activated_at)
        # The durable link is the opaque id, which of course remains.
        self.assertEqual(req.player_id, self.alice_id)

    def test_no_claimed_name_survives_anywhere_in_the_request_table(self):
        self.onboard_fully(self.alice_id)
        names = [r.claimed_name for r in PlayerRegistrationRequest.query.all()]
        self.assertEqual([n for n in names if n], [])

    def test_credential_row_stores_no_name(self):
        self.onboard_fully(self.alice_id)
        cred = PasskeyCredential.query.one()
        blob = json.dumps({c.name: str(getattr(cred, c.name))
                           for c in cred.__table__.columns})
        self.assertNotIn('Alice', blob)
        self.assertNotIn('Nováková', blob)

    def test_audit_log_records_lifecycle_without_names(self):
        from coach.models import AuditEvent
        self.onboard_fully(self.alice_id)
        rows = AuditEvent.query.filter(AuditEvent.event.like('player_access.%')
                                       | AuditEvent.event.like('passkey.%')).all()
        events = {r.event for r in rows}
        self.assertIn('player_access.requested', events)
        self.assertIn('player_access.approved', events)
        self.assertIn('passkey.registered', events)
        for r in rows:
            self.assertNotIn('Alice', r.meta or '')
            self.assertNotIn('Nováková', r.meta or '')
        # The pseudonymous id IS recorded — that is the point of the design.
        self.assertTrue(any('"player_id": %d' % self.alice_id in (r.meta or '')
                            for r in rows))


# =========================================================================
class AttendanceAuthorizationTest(IdentityTestBase):
    """§10 / §25 — a player may write only their own attendance."""

    def entry(self, player_id, team_id=None):
        return AttendanceEntry.query.filter_by(team_id=team_id or self.tid,
                                               player_id=player_id).first()

    def test_verified_player_updates_own_attendance(self):
        self.login_verified(self.alice_id)
        r = self.client.post('/attendance/set', data={
            'player_id': self.alice_id, 'event_key': self.ev_key, 'status': 'going'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.entry(self.alice_id).status, 'going')

    def test_forged_player_id_is_ignored_not_honoured(self):
        """Posting somebody else's id writes to the SESSION's player instead."""
        self.login_verified(self.alice_id)
        self.client.post('/attendance/set', data={
            'player_id': self.bob_id, 'event_key': self.ev_key, 'status': 'going'})
        self.assertIsNone(self.entry(self.bob_id))
        self.assertIsNotNone(self.entry(self.alice_id))
        self.assertEqual(self.entry(self.alice_id).status, 'going')

    def test_forged_player_id_cannot_overwrite_an_existing_entry(self):
        db.session.add(AttendanceEntry(team_id=self.tid, player_id=self.bob_id,
                                       event_key=self.ev_key, event_title='Trénink',
                                       event_day=date.today() + timedelta(days=2),
                                       status='not_going'))
        db.session.commit()
        self.login_verified(self.alice_id)
        self.client.post('/attendance/set', data={
            'player_id': self.bob_id, 'event_key': self.ev_key, 'status': 'going'})
        db.session.expire_all()
        self.assertEqual(self.entry(self.bob_id).status, 'not_going')   # untouched

    def test_cross_team_player_id_is_denied(self):
        self.login_verified(self.alice_id)
        self.client.post('/attendance/set', data={
            'player_id': self.foreign_id, 'event_key': self.ev_key, 'status': 'going'})
        self.assertIsNone(self.entry(self.foreign_id, self.other_tid))

    def test_session_from_another_team_cannot_write_here(self):
        """A player_id that does not belong to the session's team is refused."""
        self.login_verified(self.foreign_id, team_id=self.tid)   # mismatched pair
        r = self.client.post('/attendance/set', data={
            'player_id': self.foreign_id, 'event_key': self.ev_key, 'status': 'going'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(AttendanceEntry.query.count(), 0)

    def test_shared_player_key_session_cannot_mutate(self):
        """§14 — the legacy key must not grant individual attendance edits."""
        self.login_player_key()
        r = self.client.post('/attendance/set', data={
            'player_id': self.alice_id, 'event_key': self.ev_key, 'status': 'going'})
        self.assertEqual(r.status_code, 302)
        self.assertIn('/player/onboarding', r.headers.get('Location', ''))
        self.assertEqual(AttendanceEntry.query.count(), 0)

    def test_pending_claimant_cannot_act_as_the_claimed_player(self):
        """§11 — before approval the user has none of the claimed permissions."""
        self.login_player_key()
        self.claim(self.alice_id)
        self.client.post('/attendance/set', data={
            'player_id': self.alice_id, 'event_key': self.ev_key, 'status': 'going'})
        self.assertEqual(AttendanceEntry.query.count(), 0)
        self.assertIsNone(self.session_value('player_id'))

    def test_rejected_claimant_never_gains_access(self):
        self.login_player_key()
        self.claim(self.bob_id)
        req_id = self.latest_request().id
        coach = app.test_client()
        self.login_coach(client=coach)
        coach.post('/team/player-access/%d/reject' % req_id)
        self.client.post('/attendance/set', data={
            'player_id': self.bob_id, 'event_key': self.ev_key, 'status': 'going'})
        self.assertEqual(AttendanceEntry.query.count(), 0)
        self.assertIsNone(self.session_value('player_id'))

    def test_coach_team_management_still_works(self):
        self.login_coach()
        for pid in (self.alice_id, self.bob_id):
            r = self.client.post('/attendance/set', data={
                'player_id': pid, 'event_key': self.ev_key, 'status': 'going'})
            self.assertEqual(r.status_code, 302)
        self.assertEqual(AttendanceEntry.query.filter_by(team_id=self.tid).count(), 2)

    def test_coach_cannot_manage_another_teams_player(self):
        self.login_coach()
        self.client.post('/attendance/set', data={
            'player_id': self.foreign_id, 'event_key': self.ev_key, 'status': 'going'})
        self.assertEqual(AttendanceEntry.query.count(), 0)

    def test_coach_ajax_cell_still_works(self):
        self.login_coach()
        r = self.client.post('/attendance/cell',
                             json={'player_id': self.alice_id, 'event_key': self.ev_key,
                                   'status': 'maybe'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()['ok'])

    def test_verified_player_cannot_use_the_coach_team_matrix(self):
        """/dochazka bulk POST stays coach-only — including for their own row."""
        self.login_verified(self.alice_id)
        ev_id = self.ev_key.split(':')[1]
        r = self.client.post('/dochazka', data={
            'status_local:%s_%d' % (ev_id, self.bob_id): 'going',
            'status_local:%s_%d' % (ev_id, self.alice_id): 'going'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(AttendanceEntry.query.count(), 0)

    def test_verified_player_cannot_use_the_coach_ajax_cell(self):
        self.login_verified(self.alice_id)
        r = self.client.post('/attendance/cell',
                             json={'player_id': self.alice_id, 'event_key': self.ev_key,
                                   'status': 'maybe'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(AttendanceEntry.query.count(), 0)


# =========================================================================
class AttendanceUiScopeTest(IdentityTestBase):
    """§21 — the UI must not offer another player's controls."""

    def test_verified_player_page_is_pinned_to_self(self):
        self.login_verified(self.alice_id)
        html = self.client.get('/attendance?player_id=%d' % self.bob_id).get_data(as_text=True)
        self.assertIn('Alice Nováková', html)
        self.assertNotIn('Bob Svoboda', html)          # no picker, no other player

    # NOTE: assert on rendered ATTRIBUTES, not bare selector strings — the inline
    # scripts mention '[data-pa-form]' etc. and would match either way.
    DESKTOP_RSVP = 'name="event_key"'          # hidden input inside the POST form
    MOBILE_RSVP = 'data-status="going"'        # one-tap RSVP button
    MOBILE_PICKER = 'id="pamPlayerSheet"'

    def test_shared_key_session_never_reaches_the_attendance_page(self):
        """The global gate bounces it before any attendance markup is rendered."""
        self.login_player_key()
        r = self.client.get('/attendance?player_id=%d' % self.alice_id)
        self.assertEqual(r.status_code, 302)
        self.assertIn('/player/onboarding', r.headers.get('Location', ''))

    def test_verified_player_sees_editable_controls_on_both_layouts(self):
        self.login_verified(self.alice_id)
        html = self.client.get('/attendance').get_data(as_text=True)
        self.assertIn(self.DESKTOP_RSVP, html)          # desktop
        self.assertIn(self.MOBILE_RSVP, html)           # mobile
        self.assertNotIn(self.MOBILE_PICKER, html)      # mobile picker not rendered

    def test_coach_keeps_the_player_picker(self):
        self.login_coach()
        html = self.client.get('/attendance?player_id=%d' % self.alice_id).get_data(as_text=True)
        self.assertIn('pa-player', html)
        self.assertIn('Bob Svoboda', html)


# =========================================================================
class SessionHygieneTest(IdentityTestBase):
    """§18 — no identity leaks between logins."""

    def test_logout_clears_every_identity_key(self):
        self.onboard_fully(self.alice_id)
        self.client.get('/team/logout')
        for key in ('team_id', 'team_role', 'team_login', 'player_id',
                    'auth_method', 'onboarding_claim_token'):
            self.assertIsNone(self.session_value(key), key)

    def test_player_then_coach_login_leaves_no_player_id(self):
        self.onboard_fully(self.alice_id)
        self.assertEqual(self.session_value('player_id'), self.alice_id)
        self.login_coach()                       # same browser, coach key
        self.assertIsNone(self.session_value('player_id'))
        self.assertEqual(self.session_value('team_role'), 'coach')
        self.assertEqual(self.session_value('auth_method'), 'team_key')

    def test_player_a_then_player_b_does_not_leak(self):
        auth_a = self.onboard_fully(self.alice_id)
        auth_b = self.onboard_fully(self.bob_id, client=app.test_client())
        shared = app.test_client()
        self.login_passkey(auth_a, client=shared)
        self.assertEqual(self.session_value('player_id', shared), self.alice_id)
        self.login_passkey(auth_b, client=shared)
        self.assertEqual(self.session_value('player_id', shared), self.bob_id)
        # and A's attendance is now untouchable from this session
        shared.post('/attendance/set', data={'player_id': self.alice_id,
                                             'event_key': self.ev_key, 'status': 'going'})
        self.assertIsNone(AttendanceEntry.query.filter_by(player_id=self.alice_id).first())
        self.assertIsNotNone(AttendanceEntry.query.filter_by(player_id=self.bob_id).first())

    def test_coach_then_player_login_drops_the_coach_role(self):
        self.login_coach()
        auth = self.onboard_fully(self.alice_id, client=app.test_client())
        self.login_passkey(auth)                 # same browser that was coach
        self.assertEqual(self.session_value('team_role'), 'player')
        self.assertEqual(self.session_value('player_id'), self.alice_id)
        self.assertEqual(self.client.get('/attendance/import').status_code, 302)


# =========================================================================
class LegacyAndAccessGateTest(IdentityTestBase):
    """§14 / §28 — backward compatibility and route gating."""

    def test_existing_coach_key_login_still_works(self):
        r = self.login_coach()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.session_value('team_role'), 'coach')
        self.assertEqual(self.client.get('/players').status_code, 200)
        self.assertEqual(self.client.get('/attendance/import').status_code, 200)

    def test_shared_player_key_reaches_onboarding_and_nothing_else(self):
        self.login_player_key()
        self.assertEqual(self.client.get('/player/onboarding').status_code, 200)
        for path in ('/app', '/players', '/attendance', '/dochazka', '/roster',
                     '/lines', '/drills', '/nastenka', '/pokladna', '/settings',
                     '/lineup-sessions', '/drill-sessions'):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 302, path)
            self.assertIn('/player/onboarding', r.headers.get('Location', ''), path)

    def test_passkey_login_endpoints_are_reachable_without_a_session(self):
        anon = app.test_client()
        self.assertEqual(anon.post('/passkey/login/options').status_code, 200)
        r = anon.post('/passkey/login/verify', json={})
        self.assertEqual(r.status_code, 400)          # reached the view, rejected input

    def test_registration_endpoints_refuse_without_a_claim(self):
        """Registration is reachable without a session (a returning browser has
        only its resume cookie) but refuses outright without a live approved
        claim — so anonymity still mints nothing."""
        anon = app.test_client()
        r = anon.post('/passkey/register/options')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()['error'], 'not_found')
        r = anon.post('/passkey/register/verify', json={'credential': {}})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(PasskeyCredential.query.count(), 0)

    def test_coach_access_page_is_coach_only(self):
        self.login_player_key()
        r = self.client.get('/team/player-access')
        self.assertEqual(r.status_code, 302)

    def test_coach_is_redirected_from_player_onboarding(self):
        self.login_coach()
        r = self.client.get('/player/onboarding')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/team/player-access', r.headers.get('Location', ''))


if __name__ == '__main__':
    unittest.main()
