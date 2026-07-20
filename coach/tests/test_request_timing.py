# -*- coding: utf-8 -*-
"""Phase 2 — central request timing / slow-request logging.

Verifies the before/after_request timing hooks never break a normal request,
that a slow request (threshold lowered to 0) is logged at WARNING with the
safe, non-PII fields, and that the per-request query counter is wired.
"""
import os
import re
import unittest

from coach.app import app
from coach.extensions import db
from coach.models import Team, TeamKey
from coach.services.keys import hash_team_key


class RequestTimingTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='HC Test'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('ck')))
        db.session.commit()
        self.client = app.test_client()
        self._prev_threshold = os.environ.get('SLOW_REQUEST_THRESHOLD_MS')

    def tearDown(self):
        if self._prev_threshold is None:
            os.environ.pop('SLOW_REQUEST_THRESHOLD_MS', None)
        else:
            os.environ['SLOW_REQUEST_THRESHOLD_MS'] = self._prev_threshold
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self, role='coach'):
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid; s['team_role'] = role; s['team_login'] = True

    # 1: timing hooks do not break a normal request
    def test_normal_request_not_broken(self):
        self._login()
        r = self.client.get('/app')
        self.assertEqual(r.status_code, 200)

    # 2: a public request also works (no team session)
    def test_public_request_not_broken(self):
        r = self.client.get('/team/auth')
        self.assertEqual(r.status_code, 200)

    # 3: slow request (threshold 0) is logged at WARNING with safe fields + query count
    def test_slow_request_logged_with_safe_fields(self):
        os.environ['SLOW_REQUEST_THRESHOLD_MS'] = '0'
        self._login()
        with self.assertLogs(app.logger, level='WARNING') as cm:
            r = self.client.get('/app')
        self.assertEqual(r.status_code, 200)
        slow = [m for m in cm.output if '[perf] SLOW' in m]
        self.assertTrue(slow, 'expected a [perf] SLOW warning')
        line = slow[0]
        # safe, non-PII shape: method, path, status, ms, query count, endpoint, team id
        self.assertIn('GET /app', line)
        self.assertIn('-> 200', line)
        self.assertRegex(line, r'q=\d+')
        self.assertRegex(line, r'ms')
        # a DB-hitting dashboard load should have counted at least one query
        q = int(re.search(r'q=(\d+)', line).group(1))
        self.assertGreater(q, 0)
        # never leak secrets/PII
        for bad in ('password', 'csrf', 'cookie', 'session', 'token'):
            self.assertNotIn(bad, line.lower())

    # 4: threshold default is 1000ms and env override is read per request
    def test_threshold_env_override(self):
        from coach.services.request_timing import _threshold_ms
        os.environ.pop('SLOW_REQUEST_THRESHOLD_MS', None)
        self.assertEqual(_threshold_ms(), 1000)
        os.environ['SLOW_REQUEST_THRESHOLD_MS'] = '250'
        self.assertEqual(_threshold_ms(), 250)
        os.environ['SLOW_REQUEST_THRESHOLD_MS'] = 'not-a-number'
        self.assertEqual(_threshold_ms(), 1000)  # falls back safely


if __name__ == '__main__':
    unittest.main()
