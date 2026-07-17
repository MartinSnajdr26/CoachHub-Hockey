# -*- coding: utf-8 -*-
"""Owner-only Teams monitoring page + team access-key regeneration.

Covers access control (unauth / normal team session / owner), the team list and
metrics, that raw keys are never exposed in the list, POST-only regeneration,
single-active-key invalidation (old key fails, new key logs in), uniqueness /
readable format of generated keys, and isolation (only the selected team/role
changes).
"""
import re
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from coach.app import app
from coach.extensions import db
from coach.models import (Team, TeamKey, Player, TrainingEvent, AttendanceEntry,
                          Drill)
from coach.services.keys import hash_team_key, verify_team_key

KEY_RE = re.compile(r'CHH-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}')


class OwnerTeamsTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
                          ADMIN_SECRET_KEY='owner-secret', IS_DEV=False)
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        # Team A with data + keys
        self.a = Team(name='HC Alpha'); db.session.add(self.a); db.session.flush()
        self.aid = self.a.id
        self.a_coach_plain = 'coach-alpha-key'
        db.session.add(TeamKey(team_id=self.aid, role='coach',
                               key_hash=hash_team_key(self.a_coach_plain), active=True))
        db.session.add(TeamKey(team_id=self.aid, role='player',
                               key_hash=hash_team_key('player-alpha-key'), active=True))
        db.session.add(Player(team_id=self.aid, name='Hráč 1', position='F'))
        db.session.add(Player(team_id=self.aid, name='Hráč 2', position='D'))
        db.session.add(TrainingEvent(team_id=self.aid, day=date.today() + timedelta(days=2),
                                     time='18:00', title='Trénink', kind='training',
                                     source='coachhub_manual'))
        db.session.add(AttendanceEntry(team_id=self.aid, event_key='k1', player_id=1,
                                       event_day=date.today(), status='going'))
        db.session.add(Drill(team_id=self.aid, name='Cvičení 1'))
        # Team B (separate) with its own coach key
        self.b = Team(name='HC Beta'); db.session.add(self.b); db.session.flush()
        self.bid = self.b.id
        self.b_coach_plain = 'coach-beta-key'
        db.session.add(TeamKey(team_id=self.bid, role='coach',
                               key_hash=hash_team_key(self.b_coach_plain), active=True))
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login_owner(self):
        # Set the owner session directly rather than POSTing /owner/login, whose
        # rate limiter uses shared in-memory storage across the whole test run.
        with self.client.session_transaction() as s:
            s['owner_admin'] = True

    def _login_team(self, tid=None, role='coach'):
        with self.client.session_transaction() as s:
            s['team_id'] = tid or self.aid; s['team_role'] = role; s['team_login'] = True

    def _active_coach_hash(self, tid):
        tk = TeamKey.query.filter_by(team_id=tid, role='coach', active=True).first()
        return tk.key_hash if tk else None

    # 1: unauthenticated -> redirected to owner login
    def test_unauth_cannot_access(self):
        r = self.client.get('/owner/teams')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/owner/login', r.headers['Location'])

    # 2: normal team/coach session cannot access the owner page
    def test_team_session_cannot_access(self):
        self._login_team(role='coach')
        r = self.client.get('/owner/teams')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/owner/login', r.headers['Location'])

    # 3 + 4 + 5 + 6: owner can access, all teams listed, metrics render
    def test_owner_sees_all_teams_and_metrics(self):
        self._login_owner()
        r = self.client.get('/owner/teams')
        self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        self.assertIn('HC Alpha', h)
        self.assertIn('HC Beta', h)
        self.assertIn('Regenerate key', h)

    # 7: raw key hashes are never exposed in the list
    def test_list_does_not_expose_keys(self):
        self._login_owner()
        h = self.client.get('/owner/teams').get_data(as_text=True)
        self.assertNotIn(self._active_coach_hash(self.aid), h)
        self.assertNotIn('scrypt$', h)          # no hash material
        self.assertNotIn(self.a_coach_plain, h)  # no plaintext either

    # 8 + 9: regenerate is POST-only; GET does not regenerate
    def test_regenerate_is_post_only(self):
        self._login_owner()
        before = self._active_coach_hash(self.aid)
        r = self.client.get('/owner/teams/%d/regenerate-key' % self.aid)
        self.assertIn(r.status_code, (404, 405))
        self.assertEqual(self._active_coach_hash(self.aid), before)  # unchanged

    # 10: non-owner cannot regenerate
    def test_non_owner_cannot_regenerate(self):
        self._login_team(role='coach')
        before = self._active_coach_hash(self.aid)
        r = self.client.post('/owner/teams/%d/regenerate-key' % self.aid, data={'role': 'coach'})
        self.assertEqual(r.status_code, 302)
        self.assertIn('/owner/login', r.headers['Location'])
        self.assertEqual(self._active_coach_hash(self.aid), before)

    # 11 + 13 + 14 + 15: regeneration invalidates old key, new key works, shown once
    def test_regenerate_invalidates_old_and_new_works(self):
        self._login_owner()
        old_hash = self._active_coach_hash(self.aid)
        r = self.client.post('/owner/teams/%d/regenerate-key' % self.aid, data={'role': 'coach'})
        self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        # success message + the new key shown once
        self.assertIn('New team key generated. Save it now', h)
        m = KEY_RE.search(h)
        self.assertIsNotNone(m, 'readable key not displayed')
        new_key = m.group(0)
        # exactly one active coach key, and it is a different hash
        active = TeamKey.query.filter_by(team_id=self.aid, role='coach', active=True).all()
        self.assertEqual(len(active), 1)
        self.assertNotEqual(active[0].key_hash, old_hash)
        # old plaintext no longer verifies against the active key; new one does
        self.assertFalse(verify_team_key(self.a_coach_plain, active[0].key_hash))
        self.assertTrue(verify_team_key(new_key, active[0].key_hash))
        # old key row is retained but deactivated
        self.assertTrue(TeamKey.query.filter_by(team_id=self.aid, role='coach',
                                                active=False).count() >= 1)

    # 13/14 end-to-end via the real team-login flow
    def test_old_key_login_fails_new_key_login_succeeds(self):
        self._login_owner()
        h = self.client.post('/owner/teams/%d/regenerate-key' % self.aid,
                             data={'role': 'coach'}).get_data(as_text=True)
        new_key = KEY_RE.search(h).group(0)
        # fresh client (no owner session) attempts team login with the OLD key
        c = app.test_client()
        c.post('/team/login', data={'team_id': self.aid, 'role': 'coach',
                                    'key': self.a_coach_plain, 'terms_accept': 'on'})
        with c.session_transaction() as s:
            self.assertNotEqual(s.get('team_id'), self.aid)  # old key did not log in
        # new key logs in
        c2 = app.test_client()
        c2.post('/team/login', data={'team_id': self.aid, 'role': 'coach',
                                     'key': new_key, 'terms_accept': 'on'})
        with c2.session_transaction() as s:
            self.assertEqual(s.get('team_id'), self.aid)     # new key logged in
            self.assertEqual(s.get('team_role'), 'coach')

    # 16: only the selected team + role changes
    def test_only_selected_team_role_changed(self):
        self._login_owner()
        b_before = self._active_coach_hash(self.bid)
        a_player_before = TeamKey.query.filter_by(team_id=self.aid, role='player',
                                                  active=True).first().key_hash
        self.client.post('/owner/teams/%d/regenerate-key' % self.aid, data={'role': 'coach'})
        # team B untouched
        self.assertEqual(self._active_coach_hash(self.bid), b_before)
        # team A player key untouched (only coach role changed)
        self.assertEqual(TeamKey.query.filter_by(team_id=self.aid, role='player',
                                                 active=True).first().key_hash, a_player_before)

    # 12: generated keys are unique + readable format
    def test_generated_keys_unique_and_formatted(self):
        self._login_owner()
        seen = set()
        for tid in (self.aid, self.bid, self.aid, self.bid):
            h = self.client.post('/owner/teams/%d/regenerate-key' % tid,
                                 data={'role': 'coach'}).get_data(as_text=True)
            key = KEY_RE.search(h).group(0)
            self.assertNotIn(key, seen)
            seen.add(key)
        self.assertEqual(len(seen), 4)

    # Audit fix #3: the plaintext key is shown once, then never again
    def test_generated_key_shown_only_once(self):
        self._login_owner()
        h = self.client.post('/owner/teams/%d/regenerate-key' % self.aid,
                             data={'role': 'coach'}).get_data(as_text=True)
        key = KEY_RE.search(h).group(0)
        self.assertIn(key, h)                       # shown immediately after POST
        again = self.client.get('/owner/teams').get_data(as_text=True)
        self.assertNotIn(key, again)                # not persisted / not re-shown

    # Audit fix #1: regenerate forms carry the confirmation convention + message
    def test_regenerate_forms_have_confirmation(self):
        self._login_owner()
        h = self.client.get('/owner/teams').get_data(as_text=True)
        self.assertIn('form-confirm', h)
        self.assertIn('data-message', h)
        self.assertIn('invalidate the current', h)

    # Audit fix #4a: an invalid role rotates nothing
    def test_invalid_role_does_not_rotate(self):
        self._login_owner()
        coach_before = self._active_coach_hash(self.aid)
        player_before = TeamKey.query.filter_by(team_id=self.aid, role='player',
                                                active=True).first().key_hash
        r = self.client.post('/owner/teams/%d/regenerate-key' % self.aid,
                             data={'role': 'goalie'})
        self.assertEqual(r.status_code, 302)        # redirected back, no crash
        self.assertEqual(self._active_coach_hash(self.aid), coach_before)
        self.assertEqual(TeamKey.query.filter_by(team_id=self.aid, role='player',
                                                 active=True).first().key_hash, player_before)

    # Audit fix #4b: a nonexistent team_id does not crash and rotates nothing
    def test_nonexistent_team_does_not_rotate(self):
        self._login_owner()
        total_before = TeamKey.query.count()
        r = self.client.post('/owner/teams/999999/regenerate-key', data={'role': 'coach'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(TeamKey.query.count(), total_before)

    # Audit fix #5: fail closed — if a unique key can't be confirmed, abort the
    # rotation and keep the old key valid (nothing invalidated).
    def test_unique_generation_fail_closed(self):
        self._login_owner()
        fixed = 'CHH-FIXD-KEYX-TST0'
        tk = TeamKey.query.filter_by(team_id=self.aid, role='coach', active=True).first()
        tk.key_hash = hash_team_key(fixed)
        db.session.commit()
        before = tk.key_hash
        # gen always collides with the existing active key -> uniqueness never confirmed
        with patch('coach.blueprints.owner.gen_readable_key', return_value=fixed):
            r = self.client.post('/owner/teams/%d/regenerate-key' % self.aid,
                                 data={'role': 'coach'}, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn('Nepodařilo se vygenerovat unikátní klíč', r.get_data(as_text=True))
        # exactly one active coach key, unchanged, and the old key still works
        active = TeamKey.query.filter_by(team_id=self.aid, role='coach', active=True).all()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].key_hash, before)
        self.assertTrue(verify_team_key(fixed, active[0].key_hash))

    # Audit fix #6: template receives boolean key status, not TeamKey objects
    def test_team_rows_expose_booleans_only(self):
        from coach.blueprints.owner import _team_rows
        self._login_owner()
        rows = _team_rows()
        row = next(r for r in rows if r['team'].id == self.aid)
        self.assertIsInstance(row['coach_key'], bool)
        self.assertIsInstance(row['player_key'], bool)
        self.assertTrue(row['coach_key'])
        # Team B has no player key
        row_b = next(r for r in rows if r['team'].id == self.bid)
        self.assertFalse(row_b['player_key'])


class OwnerTeamsCsrfTest(unittest.TestCase):
    """Production-like: CSRF protection enabled. A regenerate POST without a valid
    csrf_token must be rejected and must NOT rotate any key."""

    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=True,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
                          ADMIN_SECRET_KEY='owner-secret', IS_DEV=False)
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.t = Team(name='HC Csrf'); db.session.add(self.t); db.session.flush()
        self.tid = self.t.id
        db.session.add(TeamKey(team_id=self.tid, role='coach',
                               key_hash=hash_team_key('coach-csrf-key'), active=True))
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()
        app.config['WTF_CSRF_ENABLED'] = False  # don't leak into other test files

    def test_regenerate_without_csrf_rejected_and_no_rotation(self):
        with self.client.session_transaction() as s:
            s['owner_admin'] = True
        before = TeamKey.query.filter_by(team_id=self.tid, role='coach',
                                         active=True).first().key_hash
        r = self.client.post('/owner/teams/%d/regenerate-key' % self.tid,
                             data={'role': 'coach'})  # no csrf_token
        self.assertEqual(r.status_code, 400)          # CSRFProtect rejects
        active = TeamKey.query.filter_by(team_id=self.tid, role='coach', active=True).all()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].key_hash, before)  # key not rotated


if __name__ == '__main__':
    unittest.main()
