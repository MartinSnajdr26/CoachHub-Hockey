# -*- coding: utf-8 -*-
"""Regression tests for the three confirmed production security fixes:

* C1 — SECRET_KEY / ADMIN_SECRET_KEY production boot guard (app.py)
* C2 — SSRF hardening: redirect re-validation + Týmuj size cap (url_safety, tymuj)
* M2 — no write-on-read AuditEvent in league get_view (service.py)
"""
import json
import os
import subprocess
import sys
import unittest
import urllib.error

from coach.app import app
from coach.extensions import db
from coach.models import AuditEvent, LeagueIntegration, Team
from coach.services import url_safety
from coach.services.url_safety import (
    UnsafeUrlError, safe_urlopen, validate_public_http_url,
)
from coach.services.league import service as league_svc

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


# --------------------------------------------------------------------------
# C1 — production boot guard (run in a subprocess so the import-time guard
# actually fires; DB_URL is forced to :memory: so dev.db is never touched).
# --------------------------------------------------------------------------
class SecretKeyBootGuardTest(unittest.TestCase):
    def _boot(self, **overrides):
        env = dict(os.environ)
        for k in ('APP_ENV', 'FLASK_ENV', 'DEBUG', 'FLASK_DEBUG',
                  'SECRET_KEY', 'ADMIN_SECRET_KEY', 'OWNER_ACCESS_KEY'):
            env.pop(k, None)
        env['DB_URL'] = 'sqlite:///:memory:'   # never touch dev.db
        env.update(overrides)
        return subprocess.run(
            [sys.executable, '-c', 'import coach.app'],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True,
        )

    def test_dev_boots_without_explicit_secret_key(self):
        r = self._boot(APP_ENV='dev')
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_prod_refuses_default_secret_key(self):
        # No SECRET_KEY in env -> .env injects the dev default -> must be rejected.
        r = self._boot(APP_ENV='production')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('SECRET_KEY', r.stderr)

    def test_prod_refuses_missing_admin_secret_key(self):
        r = self._boot(APP_ENV='production', SECRET_KEY='a-strong-unique-prod-secret')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('ADMIN_SECRET_KEY', r.stderr)

    def test_prod_boots_with_both_secrets(self):
        r = self._boot(APP_ENV='production',
                       SECRET_KEY='a-strong-unique-prod-secret',
                       ADMIN_SECRET_KEY='owner-admin-secret')
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_guard_never_prints_secret_value(self):
        r = self._boot(APP_ENV='production', SECRET_KEY='SUPERSECRETVALUE123')
        # fails on missing ADMIN, but must not echo the SECRET_KEY value
        self.assertNotIn('SUPERSECRETVALUE123', r.stderr + r.stdout)


# --------------------------------------------------------------------------
# C2 — SSRF validator + redirect hardening + size cap
# --------------------------------------------------------------------------
class _FakeHeaders(dict):
    pass


class _FakeResp:
    def __init__(self, body=b'OK'):
        self._body = body
    def read(self, n=-1):
        return self._body if n is None or n < 0 else self._body[:n]
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


class _ScriptedOpener:
    """opener.open() replays a script of responses / raised HTTPErrors."""
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
    def open(self, req, timeout=None):
        self.calls.append(req.full_url if hasattr(req, 'full_url') else req)
        action = self.script.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


def _http_redirect(location):
    return urllib.error.HTTPError(
        'http://safe.test/', 302, 'Found', _FakeHeaders({'Location': location}), None)


class SsrfValidatorTest(unittest.TestCase):
    def test_blocks_non_http_schemes(self):
        for bad in ('ftp://example.com/x', 'file:///etc/passwd', 'gopher://h/1'):
            ok, _ = validate_public_http_url(bad)
            self.assertFalse(ok, bad)

    def test_blocks_internal_literal_ips(self):
        for bad in ('http://127.0.0.1/', 'http://169.254.169.254/latest/meta-data/',
                    'http://10.0.0.5/', 'http://192.168.1.1/', 'http://[::1]/'):
            ok, _ = validate_public_http_url(bad)
            self.assertFalse(ok, bad)

    def test_allows_public_ip(self):
        ok, _ = validate_public_http_url('http://1.1.1.1/')
        self.assertTrue(ok)


class SsrfRedirectTest(unittest.TestCase):
    def setUp(self):
        # Resolve a fake public hostname to a public IP; pass IP literals through.
        self._orig = url_safety.socket.getaddrinfo
        def fake(host, port, *a, **k):
            ip = {'safe.test': '93.184.216.34', 'safe2.test': '1.1.1.1'}.get(host, host)
            return [(2, 1, 6, '', (ip, port or 80))]
        url_safety.socket.getaddrinfo = fake
        self._orig_opener = url_safety.urllib.request.build_opener

    def tearDown(self):
        url_safety.socket.getaddrinfo = self._orig
        url_safety.urllib.request.build_opener = self._orig_opener

    def _patch_opener(self, script):
        opener = _ScriptedOpener(script)
        url_safety.urllib.request.build_opener = lambda *a, **k: opener
        return opener

    def test_redirect_to_localhost_blocked(self):
        self._patch_opener([_http_redirect('http://127.0.0.1/')])
        with self.assertRaises(UnsafeUrlError):
            safe_urlopen('http://safe.test/', timeout=5)

    def test_redirect_to_metadata_blocked(self):
        self._patch_opener([_http_redirect('http://169.254.169.254/latest/meta-data/')])
        with self.assertRaises(UnsafeUrlError):
            safe_urlopen('http://safe.test/', timeout=5)

    def test_redirect_to_rfc1918_blocked(self):
        self._patch_opener([_http_redirect('http://10.1.2.3/')])
        with self.assertRaises(UnsafeUrlError):
            safe_urlopen('http://safe.test/', timeout=5)

    def test_redirect_to_public_followed(self):
        resp = _FakeResp(b'FINAL')
        self._patch_opener([_http_redirect('http://safe2.test/'), resp])
        got = safe_urlopen('http://safe.test/', timeout=5)
        self.assertIs(got, resp)

    def test_too_many_redirects_blocked(self):
        # Always redirect to another safe host -> exceeds the budget.
        self._patch_opener([_http_redirect('http://safe2.test/'),
                            _http_redirect('http://safe.test/'),
                            _http_redirect('http://safe2.test/'),
                            _http_redirect('http://safe.test/'),
                            _http_redirect('http://safe2.test/')])
        with self.assertRaises(UnsafeUrlError):
            safe_urlopen('http://safe.test/', timeout=5, max_redirects=3)


class TymujSizeCapTest(unittest.TestCase):
    def setUp(self):
        from coach.services import tymuj
        self.tymuj = tymuj
        self._orig_validate = tymuj.validate_public_http_url
        self._orig_open = tymuj.safe_urlopen
        self._orig_max = tymuj.MAX_BYTES
        tymuj.validate_public_http_url = lambda u: (True, '')
        tymuj.MAX_BYTES = 1024

    def tearDown(self):
        self.tymuj.validate_public_http_url = self._orig_validate
        self.tymuj.safe_urlopen = self._orig_open
        self.tymuj.MAX_BYTES = self._orig_max

    def test_oversized_ics_rejected(self):
        big = b'x' * (self.tymuj.MAX_BYTES + 50)
        self.tymuj.safe_urlopen = lambda *a, **k: _FakeResp(big)
        with self.assertRaises(ValueError):
            self.tymuj._fetch_ics('http://feed.test/cal.ics')

    def test_normal_ics_decoded(self):
        self.tymuj.safe_urlopen = lambda *a, **k: _FakeResp(b'BEGIN:VCALENDAR')
        self.assertEqual(self.tymuj._fetch_ics('http://feed.test/cal.ics'), 'BEGIN:VCALENDAR')


# --------------------------------------------------------------------------
# M2 — get_view must not write to the DB on a render path
# --------------------------------------------------------------------------
class NoWriteOnReadTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        team = Team(name='HC Test')
        db.session.add(team)
        db.session.commit()
        self.team_id = team.id
        data = {
            '_schema': league_svc.CACHE_SCHEMA,
            'info': {'competition_name': 'Liga', 'season': '', 'region': ''},
            'standings': [{'team_name': 'HC Test', 'position': 1, 'played': 10,
                           'wins': 7, 'draws': 1, 'losses': 2, 'score': '40:20',
                           'points': 22, 'goals_for': 40, 'goals_against': 20,
                           'plus_minus': 20}],
            'results': [], 'team_form': [], 'form_partial': False,
        }
        li = LeagueIntegration(team_id=self.team_id, enabled=True,
                               source_url='https://vysledky.com/soutez2.php?id_soutez=1',
                               connector='vysledky', highlight_team='HC Test',
                               data_json=json.dumps(data, ensure_ascii=False))
        db.session.add(li)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_get_view_does_not_insert_audit_event(self):
        before = AuditEvent.query.count()
        view = league_svc.get_view(self.team_id)
        after = AuditEvent.query.count()
        self.assertEqual(before, after, 'get_view must not write AuditEvent rows')
        self.assertTrue(view and view.get('standings'))

    def test_app_and_settings_get_do_not_insert_audit_event(self):
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['team_id'] = self.team_id
            sess['team_role'] = 'coach'
            sess['team_login'] = True
        before = AuditEvent.query.count()
        r1 = client.get('/app')
        r2 = client.get('/settings')
        after = AuditEvent.query.count()
        self.assertIn(r1.status_code, (200, 302))
        self.assertIn(r2.status_code, (200, 302))
        self.assertEqual(before, after, 'rendering /app or /settings must not write AuditEvent')


if __name__ == '__main__':
    unittest.main()
