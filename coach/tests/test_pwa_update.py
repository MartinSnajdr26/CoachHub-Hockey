# -*- coding: utf-8 -*-
"""PWA auto-update mechanism: service-worker cache strategy, immediate
activation, one-time client reload, versioned assets, and privacy guarantees.
Source-level + route-level checks; behavioural execution of sw.js (install /
activate / fetch through a version bump) is exercised by a Node SW simulation
during verification."""
import os
import re
import unittest

from coach.app import app

SW = os.path.join(app.static_folder, 'sw.js')
PWA = os.path.join(app.static_folder, 'pwa.js')


def _read(p):
    with open(p, encoding='utf-8') as f:
        return f.read()


class ServiceWorkerSourceTest(unittest.TestCase):
    def setUp(self):
        self.sw = _read(SW)
        self.pwa = _read(PWA)

    # 1. exactly one cache-name declaration
    def test_single_cache_declaration(self):
        self.assertEqual(len(re.findall(r'\bvar\s+CACHE\s*=', self.sw)), 1)

    # 2. cache version incremented (each release bumps by one)
    def test_cache_version_incremented(self):
        self.assertIn("CACHE = 'coachhub-v5'", self.sw)
        self.assertNotIn('coachhub-v4', self.sw)

    # 3/4. immediate activation
    def test_skip_waiting_and_claim(self):
        self.assertIn('self.skipWaiting()', self.sw)
        self.assertIn('self.clients.claim()', self.sw)

    # 5. old caches deleted on activate
    def test_old_caches_deleted(self):
        self.assertIn('k !== CACHE', self.sw)
        self.assertIn('caches.delete', self.sw)

    # 6/7. controllerchange => exactly one guarded reload
    def test_controllerchange_single_guarded_reload(self):
        self.assertIn("addEventListener('controllerchange'", self.pwa)
        self.assertEqual(self.pwa.count('window.location.reload()'), 1)
        self.assertIn('refreshing', self.pwa)      # loop guard
        self.assertIn('hadController', self.pwa)    # skip first-install reload

    # 8/10. navigations are network-first and never cached (no authed HTML persisted)
    def test_navigation_network_first_uncached(self):
        self.assertIn("req.mode === 'navigate'", self.sw)
        nav = self.sw[self.sw.index("req.mode === 'navigate'"):]
        nav = nav[:nav.index('return;')]
        self.assertIn('fetch(req)', nav)
        self.assertIn('OFFLINE_URL', nav)
        self.assertNotIn('cache.put', nav)          # HTML is never stored

    # 9. non-GET (POST) short-circuits before any caching
    def test_post_not_cached(self):
        self.assertIn("req.method !== 'GET'", self.sw)
        pre = self.sw[:self.sw.index("req.mode === 'navigate'")]
        self.assertIn("if (req.method !== 'GET') { return; }", pre)

    # 11. frequently-changed CSS/JS use stale-while-revalidate keyed by full URL
    def test_app_code_stale_while_revalidate(self):
        self.assertIn('isAppCode', self.sw)
        self.assertIn('(css|js)', self.sw)
        self.assertIn('cache.match(url.href)', self.sw)   # keyed by versioned URL
        self.assertIn('cache.put(url.href', self.sw)      # background revalidation writes back

    # 12. stable assets remain cache-first (keyed by path)
    def test_stable_assets_cache_first(self):
        self.assertIn('url.origin + url.pathname', self.sw)   # path key for stable assets

    # 13. sw.js is not stored in the application cache (not precached)
    def test_sw_not_precached(self):
        precache = self.sw[self.sw.index('PRECACHE'):self.sw.index('isAppCode')]
        self.assertNotIn('sw.js', precache)

    # 15. offline fallback preserved
    def test_offline_fallback(self):
        self.assertIn("OFFLINE_URL = '/static/offline.html'", self.sw)
        self.assertIn('caches.match(OFFLINE_URL)', self.sw)
        self.assertIn('OFFLINE_URL', self.sw[self.sw.index('PRECACHE'):self.sw.index('isAppCode')])


class ServiceWorkerRouteTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    # 13. /sw.js served with JS type, root scope, no-cache (never cached by its own cache)
    def test_sw_route_headers(self):
        r = self.client.get('/sw.js')
        self.assertEqual(r.status_code, 200)
        self.assertIn('javascript', r.headers.get('Content-Type', ''))
        self.assertIn('no-cache', r.headers.get('Cache-Control', ''))
        self.assertEqual(r.headers.get('Service-Worker-Allowed'), '/')

    # 14. versioned asset URLs are rendered (stable per-release ?v=)
    def test_versioned_asset_urls_rendered(self):
        h = self.client.get('/').get_data(as_text=True)
        self.assertRegex(h, r'style\.css\?v=v5')
        self.assertRegex(h, r'app\.js\?v=v5')
        self.assertNotIn('v=csp_nonce', h)

    def test_manifest_served_and_valid(self):
        import json
        r = self.client.get('/static/manifest.webmanifest')
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.get_data(as_text=True))
        self.assertEqual(data['scope'], '/')


if __name__ == '__main__':
    unittest.main()
