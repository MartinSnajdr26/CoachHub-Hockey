# -*- coding: utf-8 -*-
"""Calendar 2.0 — recurring events: generation, create/edit/delete, attendance."""
import unittest
from datetime import date, timedelta

from coach.app import app
from coach.extensions import db
from coach.models import AttendanceEntry, Player, Team, TeamKey, TrainingEvent
from coach.services import recurrence as rec
from coach.services.keys import hash_team_key


# ----------------------------- pure generation -----------------------------
class GenerateTest(unittest.TestCase):
    def test_daily_count(self):
        d, capped = rec.generate_dates(date(2026, 9, 1), 'daily', count=5)
        self.assertEqual(d, [date(2026, 9, 1) + timedelta(days=i) for i in range(5)])
        self.assertFalse(capped)

    def test_daily_until(self):
        d, _ = rec.generate_dates(date(2026, 9, 1), 'daily', until=date(2026, 9, 3))
        self.assertEqual(d, [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)])

    def test_weekly_single_weekday(self):
        # start Mon 2026-09-07; weekly Mondays, 3x
        d, _ = rec.generate_dates(date(2026, 9, 7), 'weekly', weekdays=['MO'], count=3)
        self.assertEqual(d, [date(2026, 9, 7), date(2026, 9, 14), date(2026, 9, 21)])

    def test_weekly_multiple_weekdays(self):
        # Mon+Wed from Mon 2026-09-07 until 2026-09-17
        d, _ = rec.generate_dates(date(2026, 9, 7), 'weekly', weekdays=['MO', 'WE'],
                                  until=date(2026, 9, 17))
        self.assertEqual(d, [date(2026, 9, 7), date(2026, 9, 9), date(2026, 9, 14), date(2026, 9, 16)])

    def test_biweekly(self):
        d, _ = rec.generate_dates(date(2026, 9, 7), 'biweekly', weekdays=['MO'], count=3)
        self.assertEqual(d, [date(2026, 9, 7), date(2026, 9, 21), date(2026, 10, 5)])

    def test_monthly_skips_short_months(self):
        # 31st monthly: Jan, Mar, May... skip Feb/Apr
        d, _ = rec.generate_dates(date(2026, 1, 31), 'monthly', count=3)
        self.assertEqual(d, [date(2026, 1, 31), date(2026, 3, 31), date(2026, 5, 31)])

    def test_cap(self):
        d, capped = rec.generate_dates(date(2026, 1, 1), 'daily', count=500)
        self.assertEqual(len(d), rec.MAX_OCCURRENCES)
        self.assertTrue(capped)

    def test_requires_end_condition(self):
        d, _ = rec.generate_dates(date(2026, 1, 1), 'daily')
        self.assertEqual(d, [])


# ----------------------------- route behaviour -----------------------------
class CalendarRoutesTest(unittest.TestCase):
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

    def _events(self):
        return TrainingEvent.query.filter_by(team_id=self.tid).order_by(TrainingEvent.day.asc()).all()

    def test_single_event_unchanged(self):
        self._login()
        self.client.post('/calendar/add', data={'day': '2026-09-07', 'time_hour': '18',
                                                 'time_minute': '30', 'title': 'Trénink', 'kind': 'training'})
        evs = self._events()
        self.assertEqual(len(evs), 1)
        self.assertIsNone(evs[0].series_id)
        self.assertEqual(evs[0].source, 'coachhub_manual')
        self.assertEqual(evs[0].time, '18:30')

    def test_create_weekly_series(self):
        self._login()
        self.client.post('/calendar/add', data={'day': '2026-09-07', 'time_hour': '18',
                                                 'time_minute': '30', 'title': 'Trénink', 'kind': 'training',
                                                 'repeat': 'weekly', 'weekday': ['MO', 'WE'], 'count': '4'})
        evs = self._events()
        self.assertEqual(len(evs), 4)
        sids = {e.series_id for e in evs}
        self.assertEqual(len(sids), 1)
        self.assertTrue(all(e.source == 'coachhub_recurring' for e in evs))
        self.assertTrue(all(e.recurrence_rule == 'weekly:MO,WE' for e in evs))

    def test_create_requires_end_condition(self):
        self._login()
        self.client.post('/calendar/add', data={'day': '2026-09-07', 'title': 'T', 'kind': 'training',
                                                 'repeat': 'daily'})
        self.assertEqual(len(self._events()), 0)

    def test_create_caps_occurrences(self):
        self._login()
        self.client.post('/calendar/add', data={'day': '2026-01-01', 'title': 'T', 'kind': 'training',
                                                 'repeat': 'daily', 'count': '500'})
        self.assertEqual(len(self._events()), rec.MAX_OCCURRENCES)

    def _make_series(self):
        self._login()
        self.client.post('/calendar/add', data={'day': '2026-09-07', 'time_hour': '18', 'time_minute': '30',
                                                 'title': 'Trénink', 'kind': 'training',
                                                 'repeat': 'weekly', 'weekday': ['MO'], 'count': '4'})
        return self._events()

    def test_edit_single_occurrence(self):
        evs = self._make_series()
        mid = evs[1]
        self.client.post('/calendar/update', data={'id': mid.id, 'title': 'Změněný',
                                                    'time_hour': '19', 'time_minute': '00',
                                                    'kind': 'training', 'scope': 'one'})
        evs2 = self._events()
        self.assertEqual(sum(1 for e in evs2 if e.title == 'Změněný'), 1)
        self.assertEqual(db.session.get(TrainingEvent, mid.id).time, '19:00')

    def test_edit_entire_series(self):
        evs = self._make_series()
        self.client.post('/calendar/update', data={'id': evs[0].id, 'title': 'Celá',
                                                    'time_hour': '20', 'time_minute': '15',
                                                    'kind': 'match', 'scope': 'series'})
        evs2 = self._events()
        self.assertTrue(all(e.title == 'Celá' and e.time == '20:15' and e.kind == 'match' for e in evs2))

    def test_edit_future_occurrences(self):
        evs = self._make_series()
        target = evs[2]
        self.client.post('/calendar/update', data={'id': target.id, 'title': 'Future',
                                                    'time_hour': '07', 'time_minute': '00',
                                                    'kind': 'training', 'scope': 'future'})
        evs2 = self._events()
        changed = [e for e in evs2 if e.title == 'Future']
        self.assertEqual(len(changed), 2)            # occurrences 3 and 4
        self.assertTrue(all(e.day >= target.day for e in changed))

    def test_delete_single_occurrence(self):
        evs = self._make_series()
        self.client.post('/calendar/delete', data={'id': evs[1].id, 'scope': 'one'})
        self.assertEqual(len(self._events()), 3)

    def test_delete_entire_series(self):
        evs = self._make_series()
        self.client.post('/calendar/delete', data={'id': evs[0].id, 'scope': 'series'})
        self.assertEqual(len(self._events()), 0)

    def test_delete_future_occurrences(self):
        evs = self._make_series()
        self.client.post('/calendar/delete', data={'id': evs[2].id, 'scope': 'future'})
        self.assertEqual(len(self._events()), 2)     # first two remain

    def test_occurrences_have_independent_attendance(self):
        evs = self._make_series()
        p = Player(team_id=self.tid, name='Jan', position='F'); db.session.add(p); db.session.commit()
        # attendance on the first occurrence only
        db.session.add(AttendanceEntry(team_id=self.tid, player_id=p.id,
                                       event_key='local:%d' % evs[0].id, status='going',
                                       event_day=evs[0].day, source='coachhub_coach'))
        db.session.commit()
        # distinct keys per occurrence; only one has an entry
        keys = {'local:%d' % e.id for e in evs}
        self.assertEqual(len(keys), 4)
        self.assertEqual(AttendanceEntry.query.filter_by(team_id=self.tid).count(), 1)

    def test_player_cannot_create(self):
        self._login('player')
        r = self.client.post('/calendar/add', data={'day': '2026-09-07', 'title': 'T', 'kind': 'training',
                                                     'repeat': 'weekly', 'count': '3'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(len(self._events()), 0)

    def test_recurrence_ui_renders(self):
        self._login()
        h = self.client.get('/app').get_data(as_text=True)
        self.assertIn('class="cal-repeat"', h)
        self.assertIn('Každé 2 týdny', h)
        self.assertIn('name="weekday"', h)

    def test_month_nav_and_dashboard_regression(self):
        self._make_series()
        self.assertEqual(self.client.get('/app?year=2026&month=9').status_code, 200)
        self.assertEqual(self.client.get('/app?year=2026&month=10').status_code, 200)

    # ---- regression for the "only 1 occurrence" bug ----
    def test_bug_weekly_wednesday_count4_creates_4(self):
        """Exact repro: weekly, Wednesday, count 4 -> 4 events, 1 series,
        all coachhub_recurring, all in attendance with distinct keys."""
        self._login()
        # 2026-09-02 is a Wednesday
        self.client.post('/calendar/add', data={
            'day': '2026-09-02', 'time_hour': '18', 'time_minute': '30',
            'title': 'Trénink', 'kind': 'training',
            'repeat': 'weekly', 'weekday': 'WE', 'count': '4'})
        evs = self._events()
        self.assertEqual(len(evs), 4)
        self.assertEqual([e.day for e in evs],
                         [date(2026, 9, 2), date(2026, 9, 9), date(2026, 9, 16), date(2026, 9, 23)])
        self.assertTrue(all(e.day.weekday() == 2 for e in evs))           # Wednesdays
        self.assertEqual(len({e.series_id for e in evs}), 1)
        self.assertTrue(all(e.source == 'coachhub_recurring' for e in evs))
        # attendance event list (wide window) includes all 4 with distinct keys
        from coach.blueprints.calendar import _collect_events_for_team
        win = _collect_events_for_team(self.tid, date(2026, 8, 1), date(2026, 12, 31))
        keys = [w['key'] for w in win]
        self.assertEqual(len(keys), 4)
        self.assertEqual(len(set(keys)), 4)
        self.assertEqual(set(keys), {'local:%d' % e.id for e in evs})

    def test_bug_count_wins_over_near_until(self):
        """The reported footgun: a near 'until' must NOT truncate a requested count."""
        self._login()
        self.client.post('/calendar/add', data={
            'day': '2026-09-02', 'time_hour': '18', 'time_minute': '00',
            'title': 'T', 'kind': 'training', 'repeat': 'weekly', 'weekday': 'WE',
            'count': '4', 'until': '2026-09-05'})          # until only 3 days out
        self.assertEqual(len(self._events()), 4)           # count wins -> 4, not 1

    def test_bug_no_weekday_defaults_to_start_weekday(self):
        self._login()
        self.client.post('/calendar/add', data={
            'day': '2026-09-02', 'time_hour': '18', 'time_minute': '00',
            'title': 'T', 'kind': 'training', 'repeat': 'weekly', 'count': '4'})
        evs = self._events()
        self.assertEqual(len(evs), 4)
        self.assertTrue(all(e.day.weekday() == 2 for e in evs))           # all Wednesdays

    def test_bug_each_occurrence_appears_in_its_month(self):
        """All occurrences render in the calendar — across the months they fall in."""
        self._login()
        # start late in Sept so occurrences spill into October
        self.client.post('/calendar/add', data={
            'day': '2026-09-23', 'time_hour': '18', 'time_minute': '00',
            'title': 'Spill', 'kind': 'training', 'repeat': 'weekly', 'weekday': 'WE', 'count': '3'})
        sep = self.client.get('/app?year=2026&month=9').get_data(as_text=True)
        octb = self.client.get('/app?year=2026&month=10').get_data(as_text=True)
        # Sept shows the 23rd & 30th; October shows the 7th -> both months render the title
        self.assertIn('Spill', sep)
        self.assertIn('Spill', octb)

    def test_bug_attendance_independent_per_occurrence(self):
        evs = self._make_series()
        p = Player(team_id=self.tid, name='Jan', position='F'); db.session.add(p); db.session.commit()
        db.session.add(AttendanceEntry(team_id=self.tid, player_id=p.id,
                                       event_key='local:%d' % evs[1].id, status='going',
                                       event_day=evs[1].day, source='coachhub_coach'))
        db.session.commit()
        rows = AttendanceEntry.query.filter_by(team_id=self.tid).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].event_key, 'local:%d' % evs[1].id)        # only that occurrence


if __name__ == '__main__':
    unittest.main()
