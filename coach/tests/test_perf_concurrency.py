# -*- coding: utf-8 -*-
"""Production performance & concurrency audit — regression tests.

Covers, without changing behavior:
- Phase 3: safe SQLite engine options are configured.
- Phase 3/E: a failed DB write rolls back and leaves the session usable.
- Phase 4: a normal dashboard load uses CACHED league data and never performs a
  live external fetch — even when the external site would fail.
- Phase 5: duplicate single-event POSTs do not create duplicate rows, while
  genuinely different events are still created.
"""
import json
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

from coach.app import app
from coach.extensions import db
from coach.models import Team, TeamKey, TrainingEvent, LeagueIntegration
from coach.services.keys import hash_team_key


class _Base(unittest.TestCase):
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

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self, role='coach'):
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid; s['team_role'] = role; s['team_login'] = True


class EngineOptionsTest(_Base):
    def test_sqlite_engine_options_present(self):
        opts = app.config.get('SQLALCHEMY_ENGINE_OPTIONS') or {}
        self.assertTrue(opts.get('pool_pre_ping'), 'pool_pre_ping must be enabled')
        # busy timeout so concurrent writers wait instead of erroring
        self.assertEqual((opts.get('connect_args') or {}).get('timeout'), 30)


class RollbackSafetyTest(_Base):
    def test_failed_write_rolls_back_and_session_recovers(self):
        from coach.services.logging import log_event
        real_commit = db.session.commit
        calls = {'n': 0}

        def boom():
            calls['n'] += 1
            raise RuntimeError('simulated commit failure')

        # Force the log_event commit to fail; it must swallow + rollback, not raise.
        with mock.patch.object(db.session, 'commit', side_effect=boom):
            log_event('test.rollback', team_id=self.tid, level='error', message='x')
        self.assertEqual(calls['n'], 1)
        # Session is usable again (rollback cleared the failed unit of work).
        self.assertEqual(db.session.query(Team).count(), 1)
        # A real write still works.
        db.session.add(TrainingEvent(team_id=self.tid, day=date.today(), time='18:00',
                                     title='ok', kind='training', source='coachhub_manual'))
        db.session.commit()
        self.assertEqual(TrainingEvent.query.count(), 1)


class CachedLeagueDashboardTest(_Base):
    def _seed_league(self):
        standings = [{'position': p, 'team_name': ('HC Cache Team' if p == 4 else 'Klub %d' % p),
                      'points': 30 - p, 'played': 18, 'score': '40:30',
                      'goals_for': 40, 'goals_against': 30, 'plus_minus': 10}
                     for p in range(1, 9)]
        data = {'_schema': 3, 'standings': standings, 'results': [],
                'team_form': ['W', 'W', 'L', 'W', 'L'], 'info': {'name': 'Liga'}}
        db.session.add(LeagueIntegration(
            team_id=self.tid, enabled=True, source_url='http://example.invalid/liga',
            connector='generic', highlight_team='HC Cache Team', resolved_team='HC Cache Team',
            data_json=json.dumps(data), last_updated=datetime.utcnow()))
        db.session.commit()

    def test_dashboard_uses_cache_and_never_fetches(self):
        self._seed_league()
        self._login()
        # If the dashboard tried to refresh live, this would be called (and raise).
        with mock.patch('coach.services.league.base.fetch_html_with_meta',
                        side_effect=AssertionError('dashboard must not fetch live league data')) as fetch:
            r = self.client.get('/app')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(fetch.call_count, 0)
        # Cached standings are actually rendered.
        self.assertIn('HC Cache Team', r.get_data(as_text=True))

    def test_dashboard_renders_even_if_cache_absent(self):
        # No league integration at all -> dashboard still renders.
        self._login()
        r = self.client.get('/app')
        self.assertEqual(r.status_code, 200)


class CalendarDedupTest(_Base):
    def _add(self, title='Trénink A', day=None, time='18:00', kind='training'):
        day = day or date.today() + timedelta(days=3)
        return self.client.post('/calendar/add', data={
            'day': day.isoformat(), 'time': time, 'title': title, 'kind': kind, 'repeat': 'none',
        }, follow_redirects=False)

    def test_identical_double_submit_creates_one_row(self):
        self._login()
        d = date.today() + timedelta(days=5)
        self._add(title='Trénink A', day=d)
        self._add(title='Trénink A', day=d)   # duplicate resubmit
        self.assertEqual(
            TrainingEvent.query.filter_by(team_id=self.tid, title='Trénink A').count(), 1)

    def test_different_event_still_created(self):
        self._login()
        d = date.today() + timedelta(days=6)
        self._add(title='Trénink A', day=d)
        self._add(title='Zápas B', day=d, kind='match')  # different -> not collapsed
        self.assertEqual(TrainingEvent.query.filter_by(team_id=self.tid).count(), 2)

    def test_player_cannot_add(self):
        self._login(role='player')
        d = date.today() + timedelta(days=7)
        self._add(title='Trénink A', day=d)
        self.assertEqual(TrainingEvent.query.filter_by(team_id=self.tid).count(), 0)


if __name__ == '__main__':
    unittest.main()
