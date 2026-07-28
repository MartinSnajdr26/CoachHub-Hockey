# -*- coding: utf-8 -*-
"""Favicon & app-icon delivery.

Covers the compact "tactics-card" favicon set that replaced the old wide
"Coach Hub" wordmark favicon: the /favicon.ico route (real multi-size ICO),
manifest icon integrity (files exist + declared sizes match actual pixels),
the service-worker cache bump, and favicon presence across every standalone
base template (including the owner-admin area, which previously relied only
on the /favicon.ico fallback).

PNG/ICO are parsed from their byte headers so these tests carry no image
dependency.
"""
import json
import os
import struct
import unittest

from coach.app import app

STATIC = app.static_folder
PKG = os.path.dirname(STATIC)
TPL = os.path.join(PKG, 'templates')


def _read(p):
    with open(p, encoding='utf-8') as f:
        return f.read()


def png_size(path):
    """(width, height) from a PNG IHDR — no Pillow needed."""
    with open(path, 'rb') as f:
        head = f.read(24)
    assert head[:8] == b'\x89PNG\r\n\x1a\n', 'not a PNG: %s' % path
    return struct.unpack('>II', head[16:24])


def ico_sizes(path):
    """Sorted list of (w, h) embedded in an .ico (0 in the header means 256)."""
    with open(path, 'rb') as f:
        data = f.read()
    assert data[:4] == b'\x00\x00\x01\x00', 'not an ICO: %s' % path
    count = struct.unpack('<H', data[4:6])[0]
    sizes = []
    for i in range(count):
        off = 6 + i * 16
        sizes.append((data[off] or 256, data[off + 1] or 256))
    return sorted(sizes)


FAVICON_PNGS = {
    'favicon-16.png': (16, 16),
    'favicon-32.png': (32, 32),
    'favicon-48.png': (48, 48),
    'favicon-192.png': (192, 192),
    'favicon-512.png': (512, 512),
}


class FaviconAssetsTest(unittest.TestCase):
    def test_favicon_pngs_exist_and_match_declared_size(self):
        for name, wh in FAVICON_PNGS.items():
            p = os.path.join(STATIC, name)
            self.assertTrue(os.path.exists(p), '%s missing' % name)
            self.assertEqual(png_size(p), wh, '%s wrong dimensions' % name)

    def test_favicon_ico_has_16_32_48(self):
        p = os.path.join(STATIC, 'favicon.ico')
        self.assertTrue(os.path.exists(p), 'favicon.ico missing')
        sizes = ico_sizes(p)
        for req in ((16, 16), (32, 32), (48, 48)):
            self.assertIn(req, sizes, 'favicon.ico missing %r (has %r)' % (req, sizes))


class FaviconRouteTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_favicon_ico_route_serves_real_ico(self):
        r = self.client.get('/favicon.ico')
        self.assertEqual(r.status_code, 200)
        self.assertIn(r.headers.get('Content-Type', ''),
                      ('image/x-icon', 'image/vnd.microsoft.icon'))
        # real ICO magic (reserved=0, type=1) — never a PNG
        self.assertEqual(r.get_data()[:4], b'\x00\x00\x01\x00')


class ManifestIconsTest(unittest.TestCase):
    def test_icon_files_exist_and_dimensions_match_declared(self):
        m = json.loads(_read(os.path.join(STATIC, 'manifest.webmanifest')))
        self.assertTrue(m['icons'], 'manifest has no icons')
        for icon in m['icons']:
            path = os.path.join(PKG, icon['src'].lstrip('/'))
            self.assertTrue(os.path.exists(path), '%s missing on disk' % icon['src'])
            dw, dh = (int(x) for x in icon['sizes'].split('x'))
            self.assertEqual(png_size(path), (dw, dh),
                             '%s actual dims != declared %s' % (icon['src'], icon['sizes']))

    def test_any_icons_use_new_compact_favicon(self):
        m = json.loads(_read(os.path.join(STATIC, 'manifest.webmanifest')))
        any_srcs = [i['src'] for i in m['icons'] if i.get('purpose') == 'any']
        self.assertEqual(sorted(any_srcs),
                         ['/static/favicon-192.png', '/static/favicon-512.png'])


class ServiceWorkerCacheTest(unittest.TestCase):
    def setUp(self):
        self.sw = _read(os.path.join(STATIC, 'sw.js'))

    def test_cache_version_is_v7(self):
        self.assertIn("CACHE = 'coachhub-v7'", self.sw)
        self.assertNotIn('coachhub-v6', self.sw)

    def test_new_favicon_precached(self):
        self.assertIn('/static/favicon.ico', self.sw)
        self.assertIn('/static/favicon-192.png', self.sw)


class TemplateFaviconTest(unittest.TestCase):
    STANDALONE = ['base.html', 'owner_base.html', 'team_auth.html',
                  'welcome.html', '429.html']

    def test_all_standalone_templates_include_favicon_partial(self):
        for t in self.STANDALONE:
            self.assertIn('_favicon.html', _read(os.path.join(TPL, t)),
                          '%s does not include the favicon partial' % t)

    def test_owner_base_declares_favicon(self):
        # owner pages previously relied only on the /favicon.ico fallback
        self.assertIn('_favicon.html', _read(os.path.join(TPL, 'owner_base.html')))

    def test_partial_references_full_favicon_set(self):
        p = _read(os.path.join(TPL, '_favicon.html'))
        for f in ('favicon-16.png', 'favicon-32.png', 'favicon-48.png',
                  'favicon.ico', 'favicon-192.png'):
            self.assertIn(f, p, 'favicon partial missing %s' % f)
        self.assertNotIn('icon-192.png"', p)  # no leftover wordmark reference

    def test_welcome_page_renders_favicon_links(self):
        html = app.test_client().get('/').get_data(as_text=True)
        self.assertIn('favicon-32.png', html)
        self.assertIn('rel="apple-touch-icon"', html)


if __name__ == '__main__':
    unittest.main()
