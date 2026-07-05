# -*- coding: utf-8 -*-
"""Saved training-session WhatsApp share: rich Czech message + link.
Covers the pure message builder and the rendered menu item (team-scoped,
card/menu structure preserved, no secrets)."""
import unittest
from urllib.parse import unquote

from coach.app import app
from coach.extensions import db
from coach.models import Drill, Team, TeamKey, TrainingSession
from coach.services import session_share as ss
from coach.services.keys import hash_team_key


class ShareMessageHelperTest(unittest.TestCase):
    # 1/2/3/6. title, drill count, date, absolute url all present
    def test_full_message(self):
        m = ss.format_session_share_message('Trénink Á', '5. 2. 2026', 6, 90, 'https://host/drill-sessions/12')
        self.assertIn('Trénink Á', m)
        self.assertIn('Počet cvičení: 6', m)
        self.assertIn('Vytvořeno: 5. 2. 2026', m)
        self.assertIn('Celková délka: 90 min', m)
        self.assertIn('https://host/drill-sessions/12', m)
        self.assertEqual(m.count('https://host/drill-sessions/12'), 1)  # link exactly once

    # 4/5. duration included only when available; no empty label otherwise
    def test_duration_optional(self):
        self.assertIn('Celková délka: 45 min', ss.format_session_share_message('T', '1. 1. 2026', 3, 45, 'u'))
        no = ss.format_session_share_message('T', '1. 1. 2026', 3, 0, 'u')
        self.assertNotIn('Celková délka', no)
        self.assertNotIn('délka:', no)

    # 7. Czech characters encode + round-trip
    def test_czech_encoding(self):
        url = ss.session_whatsapp_url('Nábor brankářů č.1', '5. 2. 2026', 2, 0, 'https://h/x')
        self.assertTrue(url.startswith('https://wa.me/?text='))
        self.assertNotIn(' ', url)
        self.assertIn('Nábor brankářů', unquote(url.split('text=', 1)[1]))

    # 8. no secrets/keys/ids leaked into the visible text
    def test_no_secrets(self):
        m = ss.format_session_share_message('T', '1. 1. 2026', 3, 45, 'https://h/drill-sessions/9')
        for leak in ('team_id', 'coach_key', 'player_key', 'session_token', 'csrf', 'secret'):
            self.assertNotIn(leak, m)


class ShareRenderTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='HC One'); self.other = Team(name='HC Two')
        db.session.add_all([self.team, self.other]); db.session.flush()
        self.tid, self.oid = self.team.id, self.other.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('ck')))
        d1 = Drill(team_id=self.tid, name='Bruslení', category='R', duration=30)
        d2 = Drill(team_id=self.tid, name='Přihrávky', category='U', duration=60)
        db.session.add_all([d1, d2]); db.session.flush()
        self.sess = TrainingSession(team_id=self.tid, title='Tréninková jednotka Čtvrtek',
                                    filename='drills-x.pdf', drill_ids='%d,%d' % (d1.id, d2.id))
        self.other_sess = TrainingSession(team_id=self.oid, title='Cizí trénink',
                                          filename='drills-y.pdf', drill_ids='')
        db.session.add_all([self.sess, self.other_sess]); db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self, team_id=None, role='coach'):
        with self.client.session_transaction() as s:
            s['team_id'] = team_id or self.tid; s['team_role'] = role; s['team_login'] = True

    # 9/10. WhatsApp action renders with rich message; menu structure preserved
    def test_menu_item_rich_message(self):
        self._login()
        h = self.client.get('/drill-sessions').get_data(as_text=True)
        self.assertIn('Sdílet přes WhatsApp', h)           # relabelled action present
        self.assertIn('https://wa.me/?text=', h)           # wa.me share link
        self.assertIn('target="_blank"', h)
        self.assertIn('rel="noopener noreferrer"', h)
        self.assertIn('class="tsl-menu"', h)               # overflow menu intact
        # the encoded message carries title + drill count + total duration
        wa = h.split('https://wa.me/?text=', 1)[1].split('"', 1)[0]
        msg = unquote(wa)
        self.assertIn('Tréninková jednotka Čtvrtek', msg)
        self.assertIn('Počet cvičení: 2', msg)
        self.assertIn('Celková délka: 90 min', msg)        # 30 + 60
        self.assertIn('/drill-sessions/%d' % self.sess.id, msg)   # absolute detail link
        self.assertEqual(msg.count('/drill-sessions/%d' % self.sess.id), 1)

    # 11. team isolation — one team's page never shows another team's session/share
    def test_team_isolation(self):
        self._login(team_id=self.tid)
        h = self.client.get('/drill-sessions').get_data(as_text=True)
        self.assertIn('Tréninková jednotka Čtvrtek', h)
        self.assertNotIn('Cizí trénink', h)
        self.assertNotIn('/drill-sessions/%d' % self.other_sess.id, h)


if __name__ == '__main__':
    unittest.main()
