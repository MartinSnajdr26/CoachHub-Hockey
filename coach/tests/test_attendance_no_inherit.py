# -*- coding: utf-8 -*-
"""Regression: newly created (incl. recurring) events must NEVER inherit
attendance. Root cause was orphaned attendance + reused local:<id> keys."""
import unittest
from datetime import date

from coach.app import app
from coach.extensions import db
from coach.models import AttendanceEntry, Player, Team, TeamKey, TrainingEvent
from coach.blueprints.calendar import _collect_events_for_team
from coach.services.keys import hash_team_key


class NoInheritTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='T'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('ck')))
        self.p = Player(team_id=self.tid, name='Jan', position='F')
        db.session.add(self.p); db.session.commit()
        self.client = app.test_client()
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid; s['team_role'] = 'coach'; s['team_login'] = True

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _events(self):
        return TrainingEvent.query.order_by(TrainingEvent.day.asc(), TrainingEvent.id.asc()).all()

    def _att(self, ev):
        return AttendanceEntry.query.filter_by(team_id=self.tid, event_key='local:%d' % ev.id).all()

    def _set(self, ev, status='going'):
        self.client.post('/attendance/cell', json={'player_id': self.p.id,
                                                    'event_key': 'local:%d' % ev.id, 'status': status})

    def test_single_event_empty(self):
        self.client.post('/calendar/add', data={'day': '2026-09-02', 'time_hour': '18',
                                                 'time_minute': '0', 'title': 'T', 'kind': 'training'})
        self.assertEqual(AttendanceEntry.query.count(), 0)        # calendar add writes no attendance

    def test_recurring_all_empty(self):
        self.client.post('/calendar/add', data={'day': '2026-09-02', 'time_hour': '18', 'time_minute': '0',
                                                 'title': 'T', 'kind': 'training',
                                                 'repeat': 'weekly', 'weekday': 'WE', 'count': '4'})
        evs = self._events()
        self.assertEqual(len(evs), 4)
        self.assertEqual(AttendanceEntry.query.count(), 0)
        for e in evs:
            self.assertEqual(self._att(e), [])

    def test_set_occurrence_does_not_affect_others(self):
        self.client.post('/calendar/add', data={'day': '2026-09-02', 'time_hour': '18', 'time_minute': '0',
                                                 'title': 'T', 'kind': 'training',
                                                 'repeat': 'weekly', 'weekday': 'WE', 'count': '4'})
        evs = self._events()
        self._set(evs[0])
        self.assertEqual(len(self._att(evs[0])), 1)
        for e in evs[1:]:
            self.assertEqual(self._att(e), [])
        self._set(evs[1])
        self.assertEqual(self._att(evs[0])[0].status, 'going')   # occ1 unchanged
        self.assertEqual(len(self._att(evs[1])), 1)
        self.assertEqual(self._att(evs[2]), [])

    def test_new_event_does_not_inherit_deleted_event_attendance(self):
        """The core bug: create+attend+delete, then a new event reusing the id
        must start empty."""
        self.client.post('/calendar/add', data={'day': '2026-09-02', 'time_hour': '18', 'time_minute': '0',
                                                 'title': 'Old', 'kind': 'training'})
        old = self._events()[0]
        self._set(old)
        self.assertEqual(len(self._att(old)), 1)
        self.client.post('/calendar/delete', data={'id': old.id})
        self.assertEqual(AttendanceEntry.query.count(), 0)       # delete cleans attendance (no orphan)
        # new event (may reuse the freed id) must be empty
        self.client.post('/calendar/add', data={'day': '2026-09-09', 'time_hour': '18', 'time_minute': '0',
                                                 'title': 'New', 'kind': 'training'})
        new = self._events()[0]
        self.assertEqual(self._att(new), [])

    def test_series_delete_cleans_all_attendance(self):
        self.client.post('/calendar/add', data={'day': '2026-09-02', 'time_hour': '18', 'time_minute': '0',
                                                 'title': 'T', 'kind': 'training',
                                                 'repeat': 'weekly', 'weekday': 'WE', 'count': '4'})
        evs = self._events()
        for e in evs:
            self._set(e)
        self.assertEqual(AttendanceEntry.query.count(), 4)
        self.client.post('/calendar/delete', data={'id': evs[0].id, 'scope': 'series'})
        self.assertEqual(TrainingEvent.query.count(), 0)
        self.assertEqual(AttendanceEntry.query.count(), 0)       # no orphans left behind

    def test_tymuj_attendance_not_shared_with_local(self):
        """A Týmuj-keyed attendance row must not bleed into a local event."""
        self.client.post('/calendar/add', data={'day': '2026-09-02', 'time_hour': '18', 'time_minute': '0',
                                                 'title': 'T', 'kind': 'training'})
        ev = self._events()[0]
        # attendance keyed by a tymuj-style hash key, unrelated to local:<id>
        db.session.add(AttendanceEntry(team_id=self.tid, player_id=self.p.id,
                                       event_key='abcdef0123', status='going',
                                       event_day=ev.day, source='tymuj_import'))
        db.session.commit()
        self.assertEqual(self._att(ev), [])                      # local event still empty


if __name__ == '__main__':
    unittest.main()
