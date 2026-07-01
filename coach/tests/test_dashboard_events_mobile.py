# -*- coding: utf-8 -*-
"""Mobile Dashboard event management: coach-only create/edit/delete sheets that
post to the existing calendar_add/update/delete routes. Verifies rendering,
permissions, one-shot create/edit/delete, team isolation, recurrence fields,
CSRF, unique mobile IDs, visible validation, and untouched desktop markup.
"""
import unittest
from datetime import date, timedelta

from coach.app import app
from coach.extensions import db
from coach.models import Team, TeamKey, TrainingEvent
from coach.services.keys import hash_team_key


class DashboardEventsMobileTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='HC Smíchov'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('ck')))
        self.other = Team(name='HC Soupeř'); db.session.add(self.other); db.session.flush()
        db.session.commit()
        self.client = app.test_client()
        self.today = date.today()
        self.soon = (self.today + timedelta(days=3)).isoformat()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self, role='coach', tid=None):
        with self.client.session_transaction() as s:
            s['team_id'] = tid or self.tid; s['team_role'] = role; s['team_login'] = True

    def _mk_event(self, tid=None, title='Trénink A', day=None):
        ev = TrainingEvent(team_id=tid or self.tid, day=day or (self.today + timedelta(days=2)),
                           time='18:00', title=title, kind='training', source='coachhub_manual')
        db.session.add(ev); db.session.commit()
        return ev

    # 1 + 8 + 9 + 12: coach sees controls, recurrence fields, CSRF; desktop markup intact
    def test_coach_sees_event_controls_and_desktop_intact(self):
        self._mk_event()  # so the "Spravovat" manage entry renders too
        self._login('coach')
        h = self.client.get('/app').get_data(as_text=True)
        self.assertIn('dm-ev-cta', h)
        self.assertIn('Nová akce', h)
        self.assertIn('id="dmEvCreateSheet"', h)
        self.assertIn('id="dmEvManageSheet"', h)
        # recurrence fields present
        for name in ('name="repeat"', 'name="weekday"', 'name="until"', 'name="count"'):
            self.assertIn(name, h)
        # posts to the existing routes
        self.assertIn('/calendar/add', h)
        self.assertIn('/calendar/update', h)
        self.assertIn('/calendar/delete', h)
        self.assertIn('csrf_token', h)
        # desktop calendar markup still present (unchanged desktop)
        self.assertIn('id="dash-calendar"', h)

    # 10: no duplicate mobile form/sheet IDs
    def test_no_duplicate_mobile_ids(self):
        self._mk_event()
        self._login('coach')
        h = self.client.get('/app').get_data(as_text=True)
        for uid in ('id="dmEvCreateSheet"', 'id="dmEvManageSheet"', 'id="dmEvEditSheet"',
                    'id="dmEvEditForm"', 'id="dmEvDeleteForm"'):
            self.assertEqual(h.count(uid), 1, uid)

    # 2: player sees no create/edit/delete controls
    def test_player_sees_no_event_controls(self):
        self._mk_event()
        self._login('player')
        h = self.client.get('/app').get_data(as_text=True)
        self.assertNotIn('dm-ev-cta', h)
        self.assertNotIn('id="dmEvCreateSheet"', h)
        self.assertNotIn('Nová akce', h)

    # 3 + 4: create posts to existing route and makes exactly one event
    def test_coach_create_one_event(self):
        self._login('coach')
        before = TrainingEvent.query.count()
        r = self.client.post('/calendar/add', data={'day': self.soon, 'time': '19:30',
                                                     'title': 'Nový trénink', 'kind': 'training', 'repeat': 'none'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(TrainingEvent.query.count(), before + 1)
        ev = TrainingEvent.query.filter_by(title='Nový trénink').first()
        self.assertIsNotNone(ev)
        self.assertEqual(ev.team_id, self.tid)
        self.assertEqual(ev.time, '19:30')

    def test_player_cannot_create(self):
        self._login('player')
        before = TrainingEvent.query.count()
        self.client.post('/calendar/add', data={'day': self.soon, 'title': 'X', 'kind': 'training'})
        self.assertEqual(TrainingEvent.query.count(), before)

    # 5: edit updates exactly one existing event
    def test_coach_edit_updates_existing(self):
        ev = self._mk_event(title='Před')
        self._login('coach')
        before = TrainingEvent.query.count()
        self.client.post('/calendar/update', data={'id': ev.id, 'title': 'Po', 'time': '20:00', 'kind': 'match'})
        self.assertEqual(TrainingEvent.query.count(), before)   # no new event
        upd = db.session.get(TrainingEvent, ev.id)
        self.assertEqual(upd.title, 'Po')
        self.assertEqual(upd.time, '20:00')
        self.assertEqual(upd.kind, 'match')

    # 6: delete removes the intended event
    def test_coach_delete_removes_event(self):
        ev = self._mk_event()
        self._login('coach')
        self.client.post('/calendar/delete', data={'id': ev.id})
        self.assertIsNone(db.session.get(TrainingEvent, ev.id))

    # 7: another team's event cannot be edited or deleted
    def test_other_team_event_isolated(self):
        ev_other = self._mk_event(tid=self.other.id, title='Cizí')
        self._login('coach')  # team A coach
        self.client.post('/calendar/update', data={'id': ev_other.id, 'title': 'Hacked', 'kind': 'match'})
        self.assertEqual(db.session.get(TrainingEvent, ev_other.id).title, 'Cizí')
        self.client.post('/calendar/delete', data={'id': ev_other.id})
        self.assertIsNotNone(db.session.get(TrainingEvent, ev_other.id))

    # 11: validation errors remain visible on the mobile dashboard (flash renders)
    def test_invalid_date_flash_visible(self):
        self._login('coach')
        r = self.client.post('/calendar/add', data={'day': 'not-a-date', 'title': 'X', 'kind': 'training'},
                             follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        self.assertIn('Neplatné datum.', h)
        self.assertIn('flash-stack', h)  # rendered in the visible flash area, not hidden desktop-only

    def test_recurrence_requires_until_or_count_flash(self):
        self._login('coach')
        r = self.client.post('/calendar/add', data={'day': self.soon, 'title': 'Série', 'kind': 'training',
                                                     'repeat': 'weekly', 'weekday': 'MO'}, follow_redirects=True)
        h = r.get_data(as_text=True)
        self.assertIn('opakování zadej', h)  # "U opakování zadej datum „do" nebo počet…"


if __name__ == '__main__':
    unittest.main()
