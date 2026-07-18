# -*- coding: utf-8 -*-
"""Manual "Install app" controls on the login page and dashboard, plus the
shared pwa.js install logic (standalone detection, iOS handling, appinstalled).
"""
import os
import unittest

from coach.app import app
from coach.extensions import db
from coach.models import Player, Roster, Team, TeamKey
from coach.services.keys import hash_team_key

PWA_JS = os.path.join(app.static_folder, 'pwa.js')
SW_JS = os.path.join(app.static_folder, 'sw.js')


def _read(p):
    with open(p, encoding='utf-8') as f:
        return f.read()


class InstallControlRenderTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='HC Test'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('ck')))
        p = Player(team_id=self.tid, name='Jan Novák', position='F'); db.session.add(p); db.session.flush()
        db.session.add(Roster(team_id=self.tid, player_id=p.id))
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self):
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid; s['team_role'] = 'coach'; s['team_login'] = True

    def test_login_page_has_install_card(self):
        h = self.client.get('/team/auth').get_data(as_text=True)
        self.assertIn('class="pwa-install-card"', h)
        self.assertIn('data-pwa-install', h)
        self.assertIn('hidden', h)                              # hidden by default
        self.assertIn('js-pwa-install', h)                      # real <button> hook
        self.assertIn('Používejte CoachHub Hockey jako aplikaci', h)
        self.assertIn('Nainstalovat aplikaci', h)
        self.assertIn('pwa-install.css', h)                     # styles loaded
        self.assertIn("filename='pwa.js'", h) if False else self.assertIn('pwa.js', h)  # logic loaded

    def test_dashboard_has_compact_install_card(self):
        self._login()
        h = self.client.get('/app').get_data(as_text=True)
        self.assertIn('pwa-install-card--compact', h)           # smaller variant
        self.assertIn('data-pwa-install', h)
        self.assertIn('js-pwa-install', h)
        self.assertIn('CoachHub Hockey můžete používat také jako aplikaci', h)
        self.assertIn('pwa-install.css', h)

    def test_button_is_real_button_element(self):
        h = self.client.get('/team/auth').get_data(as_text=True)
        # accessibility: install action is a real <button type="button">
        self.assertRegex(h, r'<button type="button"[^>]*class="btn btn-secondary js-pwa-install"')


class PwaJsLogicTest(unittest.TestCase):
    def setUp(self):
        self.js = _read(PWA_JS)

    def test_captures_and_defers_prompt(self):
        self.assertIn("addEventListener('beforeinstallprompt'", self.js)
        self.assertIn('e.preventDefault()', self.js)
        self.assertIn('deferredPrompt = e', self.js)
        # must NOT auto-open the prompt inside the beforeinstallprompt handler
        head = self.js[self.js.index("beforeinstallprompt"):self.js.index("appinstalled")]
        self.assertNotIn('.prompt()', head)

    def test_standalone_detection(self):
        self.assertIn("matchMedia('(display-mode: standalone)')", self.js)
        self.assertIn('navigator.standalone', self.js)
        self.assertIn('isStandalone', self.js)

    def test_shared_selector_and_update_fn(self):
        self.assertIn('[data-pwa-install]', self.js)
        self.assertIn('updatePwaInstallButtons', self.js)

    def test_ios_handling(self):
        self.assertIn('iPad|iPhone|iPod', self.js)
        self.assertIn('maxTouchPoints', self.js)                # modern iPad desktop-UA
        self.assertIn('Přidat na plochu', self.js)              # iOS instructions
        self.assertIn("role', 'dialog'", self.js)               # accessible modal

    def test_appinstalled_hides_controls(self):
        self.assertIn("addEventListener('appinstalled'", self.js)
        tail = self.js[self.js.index("appinstalled"):]
        self.assertIn('deferredPrompt = null', tail)


class CacheVersionTest(unittest.TestCase):
    def test_cache_and_asset_version_bumped(self):
        self.assertIn("CACHE = 'coachhub-v6'", _read(SW_JS))
        self.assertNotIn('coachhub-v5', _read(SW_JS))
        from coach.context import ASSET_VERSION
        self.assertEqual(ASSET_VERSION, 'v6')


if __name__ == '__main__':
    unittest.main()
