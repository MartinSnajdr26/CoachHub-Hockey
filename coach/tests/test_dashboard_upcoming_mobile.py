# -*- coding: utf-8 -*-
"""Mobile Dashboard "Další události" collapsible section.

Redesigned Home: the upcoming events (all events after the hero) live inside a
collapsible section that is CLOSED by default (data-open="0"). The section header
shows a summary count of events excluding the hero event. There is no per-item
toggle anymore — the whole section body is shown/hidden by the collapsible header.
Verifies the title, closed-by-default state, summary count, that every rest event
is rendered, and that desktop markup and event links are untouched.
"""
import unittest
from datetime import date, timedelta

from coach.app import app
from coach.extensions import db
from coach.models import Team, TeamKey, TrainingEvent
from coach.services.keys import hash_team_key


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

    # 2: obsolete per-item toggle machinery is fully gone
    def test_old_toggle_markup_removed(self):
        self._mk_events(6)
        h = self._html()
        for gone in ('id="dmUpcoming"', 'id="dmUpToggle"', 'dm-wk--extra',
                     'data-dm-extra', 'Zobrazit další události', 'Skrýt další události'):
            self.assertNotIn(gone, h)

    # 3: empty state preserved; player with no events sees no section
    def test_no_events_keeps_empty_state(self):
        h = self._html('player')
        self.assertIn('Žádná nadcházející akce', h)
        self.assertNotIn('dm-coll-title">Další události', h)

    # 4: player with only the hero event => no "Další události" section
    def test_player_one_event_no_section(self):
        self._mk_events(1)
        h = self._html('player')
        self.assertNotIn('dm-coll-title">Další události', h)

    # 5: the section is a collapsible closed by default
    def test_section_collapsed_by_default(self):
        self._mk_events(4)
        h = self._html()
        # a collapsible container exists and the closed-state CSS is present
        self.assertIn('dm-coll', h)
        self.assertIn('data-open="0"', h)

    # 6: header summary counts events excluding the hero (rest length)
    def test_summary_count_excludes_hero(self):
        self._mk_events(5)  # hero + 4 in the section
        h = self._html('player')  # player has no coach CTA to muddy the section
        self.assertIn('<span class="dm-coll-sum">4</span>', h)

    # 7: every rest event is rendered (no hidden extras)
    def test_all_rest_events_rendered(self):
        self._mk_events(6)  # hero + 5 rest
        h = self._html()
        self.assertEqual(h.count('dm-wk dm-k-training'), 5)

    # 8: event links unchanged (still point to attendance/dochazka)
    def test_event_links_unchanged(self):
        self._mk_events(4)
        h_coach = self._html('coach')
        self.assertIn('dm-wk dm-k-training', h_coach)
        self.assertIn('/dochazka', h_coach)
        db.session.remove()
        h_player = self._html('player')
        self.assertIn('/attendance', h_player)

    # 9: desktop dashboard markup remains present/untouched
    def test_desktop_markup_intact(self):
        self._mk_events(6)
        h = self._html()
        self.assertIn('id="dash-calendar"', h)

    # 10: collapsible CSS hides the closed body and rotates the chevron
    def test_collapsible_css_present(self):
        css = open('coach/static/mobile.css', encoding='utf-8').read()
        self.assertRegex(css, r'\.dm-coll\[data-open="0"\]\s+\.dm-coll-body\s*\{\s*display:\s*none')
        self.assertRegex(css, r'\.dm-coll\[data-open="1"\]\s+\.dm-coll-chev\s*\{\s*transform:\s*rotate\(180deg\)')


if __name__ == '__main__':
    unittest.main()
