# -*- coding: utf-8 -*-
"""Mobile Dashboard compact "Další události" (upcoming events) section.

Collapsed by default: only the first upcoming event after the hero is shown; the
rest carry the `hidden` attribute in the markup and are revealed by an accessible
toggle button (real button with aria-expanded/aria-controls). Verifies the title,
the default-1 preview, hidden extras, toggle-only-when-more, and that desktop
markup and event links are untouched.
"""
import unittest
from datetime import date, timedelta

from coach.app import app
from coach.extensions import db
from coach.models import Team, TeamKey, TrainingEvent
from coach.services.keys import hash_team_key

DEFAULT_VISIBLE = 1  # events shown in the section before expanding


class DashboardUpcomingMobileTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='HC Smíchov'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('ck')))
        db.session.commit()
        self.client = app.test_client()
        self.today = date.today()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self, role='coach'):
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid; s['team_role'] = role; s['team_login'] = True

    def _mk_events(self, n):
        """Create n upcoming events on distinct future days (day+1 .. day+n)."""
        for i in range(1, n + 1):
            db.session.add(TrainingEvent(
                team_id=self.tid, day=self.today + timedelta(days=i),
                time='18:00', title='Akce %d' % i, kind='training',
                source='coachhub_manual'))
        db.session.commit()

    def _html(self, role='coach'):
        self._login(role)
        return self.client.get('/app').get_data(as_text=True)

    # 1: renamed section title, old title gone
    def test_section_title_present(self):
        self._mk_events(4)
        h = self._html()
        self.assertIn('Další události', h)
        self.assertNotIn('Tento týden', h)

    # 2: empty state preserved, no section
    def test_no_events_keeps_empty_state(self):
        h = self._html()
        self.assertIn('Žádná nadcházející akce', h)
        self.assertNotIn('id="dmUpcoming"', h)
        self.assertNotIn('id="dmUpToggle"', h)

    # 3: a single upcoming event => hero only, no "Další události" section/toggle
    def test_one_event_no_section_no_toggle(self):
        self._mk_events(1)
        h = self._html()
        self.assertNotIn('id="dmUpcoming"', h)
        self.assertNotIn('id="dmUpToggle"', h)
        self.assertNotIn('dm-wk--extra', h)

    # section with exactly one event (hero + 1) shows it, no toggle, nothing hidden
    def test_section_single_event_no_toggle(self):
        self._mk_events(2)
        h = self._html()
        self.assertIn('id="dmUpcoming"', h)
        self.assertNotIn('id="dmUpToggle"', h)
        self.assertNotIn('dm-wk--extra', h)

    # 4 + 5 + 6 + 7: many events => only first visible, rest hidden in markup,
    # toggle present with accessible attributes and the expand label
    def test_many_events_collapsed_by_default(self):
        self._mk_events(6)  # hero + 5 in the section
        h = self._html()
        self.assertIn('id="dmUpcoming"', h)
        # extras beyond the first are marked collapsible AND hidden in the markup
        self.assertIn('dm-wk--extra', h)
        self.assertIn('data-dm-extra hidden', h)
        # 5 in section - 1 default preview = 4 hidden extras
        self.assertEqual(h.count('dm-wk--extra'), 4)
        self.assertEqual(h.count('data-dm-extra hidden'), 4)
        # accessible toggle, collapsed, expand wording
        self.assertIn('id="dmUpToggle"', h)
        self.assertIn('aria-expanded="false"', h)
        self.assertIn('aria-controls="dmUpcoming"', h)
        self.assertIn('Zobrazit další události', h)

    # 9: collapse label ships for the JS-driven expanded state
    def test_collapse_label_present(self):
        self._mk_events(4)
        h = self._html()
        self.assertIn('Skrýt další události', h)

    # 11: event links unchanged (still point to attendance/dochazka)
    def test_event_links_unchanged(self):
        self._mk_events(4)
        h_coach = self._html('coach')
        self.assertIn('dm-wk dm-k-training', h_coach)
        self.assertIn('/dochazka', h_coach)
        db.session.remove()
        h_player = self._html('player')
        self.assertIn('/attendance', h_player)

    # 12: desktop dashboard markup remains present/untouched
    def test_desktop_markup_intact(self):
        self._mk_events(6)
        h = self._html()
        self.assertIn('id="dash-calendar"', h)

    # Regression: `.dm-wk { display:flex }` (author rule) beats the UA
    # [hidden]{display:none}, so without an explicit override the collapsed
    # cards stay visible. mobile.css must hide `.dm-wk[hidden]`.
    def test_css_hides_hidden_cards(self):
        css = open('coach/static/mobile.css', encoding='utf-8').read()
        self.assertRegex(css, r'\.dm-wk\[hidden\]\s*\{\s*display:\s*none')


if __name__ == '__main__':
    unittest.main()
