# -*- coding: utf-8 -*-
"""Rate-limiting reliability fix.

Root cause: a low global default ("50 per hour", per-route, keyed by
request.remote_addr) counted page views + /sw.js + /favicon.ico, and behind
PythonAnywhere's proxy (no ProxyFix) every client shared the proxy IP's bucket.

Fixes verified here: assets/sw.js/favicon exempt; generous page-view backstop;
strict auth limits kept/added; ProxyFix makes the client IP trusted and
spoof-resistant; styled 429 with Retry-After.
"""
import itertools
import os
import unittest

from coach.app import app

# Process-global so every call across every test gets a DISTINCT client IP
# (in-memory limiter storage is shared for the whole test session).
_ip_seq = itertools.count(1)


class RateLimitTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = app.test_client()

    def _ip(self, xff=None):
        # Unique client IP per call (via X-Forwarded-For -> ProxyFix -> remote_addr)
        # so buckets don't bleed between assertions.
        n = next(_ip_seq)
        return {'X-Forwarded-For': xff or ('7.%d.%d.%d' % (n // 60000 % 250, n // 250 % 250, n % 250 or 1))}

    def _hammer(self, path, n, headers, method='get'):
        fn = getattr(self.client, method)
        last = None
        for i in range(n):
            last = fn(path, headers=headers)
            if last.status_code == 429:
                return i + 1, last
        return None, last

    # 2/3/4. static assets, /sw.js, manifest, icons, favicon never consume the bucket
    def test_assets_and_sw_exempt(self):
        for path in ('/static/style.css', '/sw.js', '/static/manifest.webmanifest',
                     '/static/icon-192.png', '/favicon.ico'):
            at, _ = self._hammer(path, 60, self._ip())
            self.assertIsNone(at, '%s should be exempt but 429ed at #%s' % (path, at))

    # 1/6. normal navigation is no longer throttled at the old 50/hour
    def test_normal_navigation_allowed_past_50(self):
        at, _ = self._hammer('/team/auth', 60, self._ip())
        self.assertIsNone(at)  # would have 429ed at #51 under the old limit

    # generous backstop still catches a runaway loop (300/hour)
    def test_runaway_backstop(self):
        at, _ = self._hammer('/team/auth', 305, self._ip())
        self.assertIsNotNone(at)
        self.assertGreater(at, 300)

    # 5. repeated invalid login attempts remain strictly limited (5/min)
    def test_login_bruteforce_limited(self):
        at, _ = self._hammer('/team/login', 8, self._ip(), method='post')
        self.assertIsNotNone(at)
        self.assertLessEqual(at, 6)

    # 7. owner login is now rate-limited (was unprotected)
    def test_owner_login_limited(self):
        at, _ = self._hammer('/owner/login', 14, self._ip(), method='post')
        self.assertIsNotNone(at)
        self.assertLessEqual(at, 11)

    # 11. spoofed X-Forwarded-For cannot bypass: only the proxy-appended (rightmost)
    #     IP is trusted, so a changing spoofed prefix still shares one bucket.
    def test_xff_spoof_cannot_bypass(self):
        real = '8.8.8.8'
        for i in range(5):
            self.client.post('/team/login', headers={'X-Forwarded-For': '1.2.3.%d, %s' % (i, real)})
        r = self.client.post('/team/login', headers={'X-Forwarded-For': '9.9.9.9, %s' % real})
        self.assertEqual(r.status_code, 429)  # all 6 counted against `real`, not the spoofed prefix

    # 14/15/16. styled 429 page, correct status, Retry-After preserved
    def test_styled_429_and_retry_after(self):
        _, last = self._hammer('/team/auth', 305, self._ip())
        self.assertEqual(last.status_code, 429)
        body = last.get_data(as_text=True)
        self.assertIn('Příliš mnoho požadavků', body)
        self.assertIn('Zkusit znovu', body)          # safe navigation option
        self.assertNotIn('50 per', body)             # no raw limiter text leaked
        self.assertIn('Retry-After', last.headers)


class ProxyAndConfigTest(unittest.TestCase):
    def test_proxyfix_installed(self):
        from werkzeug.middleware.proxy_fix import ProxyFix
        self.assertIsInstance(app.wsgi_app, ProxyFix)

    def test_limits_raised_from_50(self):
        src = open(os.path.join(os.path.dirname(__file__), '..', 'extensions.py'), encoding='utf-8').read()
        self.assertIn('"300 per hour"', src)
        self.assertNotIn('"50 per hour"', src)

    def test_429_template_renders(self):
        with app.test_request_context('/'):
            from flask import render_template
            html = render_template('429.html', retry_after=42)
            self.assertIn('Příliš mnoho požadavků', html)
            self.assertIn('42', html)


if __name__ == '__main__':
    unittest.main()
