# -*- coding: utf-8 -*-
"""Tests for the attendance matrix: stats service + AJAX cell endpoint."""
import json
import unittest
from datetime import date, timedelta

from coach.app import app
from coach.extensions import db
from coach.models import AttendanceEntry, Player, Team, TeamKey, TrainingEvent
from coach.services import attendance_stats as stats
from coach.services.keys import hash_team_key


def _ev(key, d, kind='training', title='T', time='18:00'):
    return {'key': key, 'day': d, 'time': time, 'title': title, 'kind': kind, 'source': 'local'}


class StatsServiceTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='T'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        self.p1 = Player(team_id=self.tid, name='Jan Novák', position='F')
        self.p2 = Player(team_id=self.tid, name='Petr Brankář', position='G')
        db.session.add_all([self.p1, self.p2]); db.session.commit()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _entry(self, pid, key, status):
        db.session.add(AttendanceEntry(team_id=self.tid, player_id=pid, event_key=key,
                                       status=status, event_day=date.today()))

    def test_event_and_player_and_team_stats(self):
        today = date(2026, 3, 1)
        events = [_ev('e1', date(2026, 2, 1)), _ev('e2', date(2026, 2, 8), kind='match'),
                  _ev('e3', date(2026, 2, 15)), _ev('e4', date(2026, 4, 1))]  # e4 upcoming
        self._entry(self.p1.id, 'e1', 'going'); self._entry(self.p1.id, 'e2', 'going')
        self._entry(self.p1.id, 'e3', 'going')   # p1 going all 3 past -> streak 3
        self._entry(self.p2.id, 'e1', 'not_going'); self._entry(self.p2.id, 'e3', 'going')
        db.session.commit()
        entries = AttendanceEntry.query.all()
        v = stats.build_matrix_view(events, [self.p1, self.p2], entries, today=today)

        e1 = next(e for e in v['events'] if e['key'] == 'e1')
        self.assertEqual(e1['summary']['going'], 1)
        self.assertEqual(e1['summary']['not_going'], 1)
        self.assertEqual(e1['summary']['total'], 2)
        self.assertEqual(e1['summary']['pct'], 50)
        self.assertEqual(e1['summary']['color'], 'red')
        self.assertEqual(e1['by_position']['G']['not_going'], 1)

        p1v = next(p for p in v['players'] if p['id'] == self.p1.id)
        self.assertEqual(p1v['summary']['going'], 3)
        self.assertEqual(p1v['summary']['total'], 4)        # 4 events in scope
        self.assertEqual(p1v['streak'], 3)
        self.assertEqual(p1v['longest_streak'], 3)
        self.assertEqual(p1v['games']['total'], 1)          # e2 is a match
        self.assertEqual(p1v['games']['going'], 1)
        self.assertEqual(len(p1v['recent']), 3)             # 3 past events

        self.assertEqual(v['team']['total_events'], 4)
        self.assertEqual(v['team']['total_games'], 1)
        self.assertEqual(v['team']['upcoming_count'], 1)
        self.assertEqual(v['team']['best_player']['name'], 'Jan Novák')
        # upcoming event e4 has no responses -> 2 unknown
        self.assertEqual(v['team']['no_response_count'], 2)

    def test_status_map_excludes_unknown(self):
        events = [_ev('e1', date(2026, 2, 1))]
        self._entry(self.p1.id, 'e1', 'going'); db.session.commit()
        v = stats.build_matrix_view(events, [self.p1, self.p2], AttendanceEntry.query.all(),
                                    today=date(2026, 3, 1))
        self.assertIn('e1', v['status_map'].get(self.p1.id, {}))
        self.assertNotIn(self.p2.id, v['status_map'])        # p2 unknown -> absent


class CellEndpointTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='T'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        self.player = Player(team_id=self.tid, name='Jan', position='F'); db.session.add(self.player)
        ev = TrainingEvent(team_id=self.tid, day=date.today() + timedelta(days=3),
                           time='18:00', title='Trénink', kind='training')
        db.session.add(ev); db.session.commit()
        self.key = 'local:%d' % ev.id
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self, role):
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid; s['team_role'] = role; s['team_login'] = True

    def test_coach_cell_update_json(self):
        self._login('coach')
        r = self.client.post('/attendance/cell', json={
            'player_id': self.player.id, 'event_key': self.key, 'status': 'going'})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body['ok'])
        self.assertEqual(body['event_summary']['going'], 1)
        e = AttendanceEntry.query.filter_by(team_id=self.tid, event_key=self.key).first()
        self.assertEqual(e.status, 'going')
        self.assertEqual(e.source, 'coachhub_coach')

    def test_player_cannot_use_coach_cell(self):
        self._login('player')
        r = self.client.post('/attendance/cell', json={
            'player_id': self.player.id, 'event_key': self.key, 'status': 'going'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(AttendanceEntry.query.count(), 0)

    def test_bad_event_rejected(self):
        self._login('coach')
        r = self.client.post('/attendance/cell', json={
            'player_id': self.player.id, 'event_key': 'local:9999', 'status': 'going'})
        self.assertEqual(r.status_code, 404)

    def test_matrix_page_renders(self):
        self._login('coach')
        r = self.client.get('/dochazka')
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        # split-pane freeze-panes structure (replaced unreliable sticky table)
        self.assertIn('am-grid', html)
        self.assertIn('id="am-main"', html)
        self.assertIn('id="am-header"', html)
        self.assertIn('id="am-left"', html)


class RangeModelTest(unittest.TestCase):
    """Shared range model used by BOTH player page and coach matrix."""
    def test_codes_and_default(self):
        self.assertEqual(stats.RANGES, ('future', 'past', 'next30', 'all'))
        self.assertEqual(stats.DEFAULT_RANGE, 'future')

    def test_normalize_maps_legacy_and_unknown(self):
        self.assertEqual(stats.normalize_range('upcoming'), 'future')
        self.assertEqual(stats.normalize_range('season'), 'all')
        self.assertEqual(stats.normalize_range('month'), 'all')
        self.assertEqual(stats.normalize_range('today'), 'next30')
        self.assertEqual(stats.normalize_range('bogus'), 'future')
        self.assertEqual(stats.normalize_range(None), 'future')
        for code in stats.RANGES:
            self.assertEqual(stats.normalize_range(code), code)

    def test_range_window(self):
        today = date(2026, 6, 15)
        self.assertEqual(stats.range_window('future', today), (today, today + timedelta(days=365)))
        self.assertEqual(stats.range_window('next30', today), (today, today + timedelta(days=30)))
        self.assertEqual(stats.range_window('past', today)[1], today - timedelta(days=1))
        s, e = stats.range_window('all', today)
        self.assertTrue(s < today < e)


class MatrixRangeFilterTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='T'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        db.session.add(Player(team_id=self.tid, name='Jan', position='F'))
        today = date.today()
        # one past-only, one within next30, one far-future-only
        for d, title in [(today - timedelta(days=10), 'Past'),
                         (today + timedelta(days=5), 'Soon'),
                         (today + timedelta(days=200), 'Far')]:
            db.session.add(TrainingEvent(team_id=self.tid, day=d, time='18:00', title=title, kind='training'))
        db.session.commit()
        self.client = app.test_client()
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid; s['team_role'] = 'coach'; s['team_login'] = True

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _headers(self, html):
        import re
        return len(re.findall(r'class="am-hcell', html))

    def test_default_is_future(self):
        html = self.client.get('/dochazka').get_data(as_text=True)
        self.assertIn('aria-pressed="true">Budoucí', html)   # future chip active
        self.assertEqual(self._headers(html), 2)             # Soon + Far

    def test_each_range(self):
        cases = {'future': 2, 'past': 1, 'next30': 1, 'all': 3}
        labels = {'future': 'Budoucí', 'past': 'Minulé', 'next30': 'Příštích 30 dní', 'all': 'Vše'}
        for rng, n in cases.items():
            html = self.client.get('/dochazka?range=%s' % rng).get_data(as_text=True)
            self.assertEqual(self._headers(html), n, rng)
            self.assertIn('aria-pressed="true">' + labels[rng], html)

    def test_legacy_values_map_safely(self):
        for legacy, expect_label in [('upcoming', 'Budoucí'), ('season', 'Vše'),
                                     ('month', 'Vše'), ('today', 'Příštích 30 dní'),
                                     ('garbage', 'Budoucí')]:
            html = self.client.get('/dochazka?range=%s' % legacy).get_data(as_text=True)
            self.assertEqual(html and 200, 200)
            self.assertIn('aria-pressed="true">' + expect_label, html)

    def test_old_filters_removed(self):
        html = self.client.get('/dochazka').get_data(as_text=True)
        self.assertNotIn('Sezóna', html)
        self.assertNotIn('Tento měsíc', html)
        self.assertNotIn('name="estatus"', html)


if __name__ == '__main__':
    unittest.main()
