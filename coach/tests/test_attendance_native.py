# -*- coding: utf-8 -*-
"""Native CoachHub attendance + import route tests."""
import io
import unittest
from datetime import date, timedelta

from coach.app import app
from coach.extensions import db
from coach.models import AttendanceEntry, Player, Team, TeamKey, TrainingEvent
from coach.services import attendance_import as ai
from coach.services.keys import hash_team_key


class NativeAttendanceTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
                          ADMIN_SECRET_KEY='owner-secret')
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.team = Team(name='HC Test')
        db.session.add(self.team)
        db.session.flush()
        self.tid = self.team.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('coach-key')))
        db.session.add(TeamKey(team_id=self.tid, role='player', key_hash=hash_team_key('player-key')))
        self.player = Player(team_id=self.tid, name='Jan Novák', position='F')
        db.session.add(self.player)
        ev = TrainingEvent(team_id=self.tid, day=date.today() + timedelta(days=2),
                           time='18:00', title='Trénink', kind='training')
        db.session.add(ev)
        db.session.commit()
        self.ev_key = 'local:%d' % ev.id
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _login(self, role):
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid
            s['team_role'] = role
            s['team_login'] = True

    def test_native_page_renders(self):
        self._login('player')
        self.assertEqual(self.client.get('/attendance').status_code, 200)
        r = self.client.get('/attendance?player_id=%d&range=upcoming' % self.player.id)
        self.assertEqual(r.status_code, 200)
        self.assertIn('Trénink', r.get_data(as_text=True))

    def test_player_page_empty_state_without_player(self):
        self._login('player')
        r = self.client.get('/attendance')
        self.assertEqual(r.status_code, 200)
        self.assertIn('Nejdřív vyber', r.get_data(as_text=True))

    def test_player_page_filters_and_default_future(self):
        self._login('player')
        # default (no range) shows the future event + summary + range buttons
        r = self.client.get('/attendance?player_id=%d' % self.player.id)
        h = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn(self.player.name, h)
        self.assertIn('Nadcházející', h)            # summary card
        for label in ('Budoucí', 'Minulé', 'Příštích 30 dní', 'Vše'):
            self.assertIn(label, h)
        # all four range values are accepted (no 500)
        for rng in ('future', 'past', 'next30', 'all', 'bogus'):
            self.assertEqual(self.client.get('/attendance?player_id=%d&range=%s'
                                             % (self.player.id, rng)).status_code, 200)

    def test_player_page_no_events_for_filter(self):
        self._login('player')
        # the only event is in the future; the 'past' filter must show empty msg
        r = self.client.get('/attendance?player_id=%d&range=past' % self.player.id)
        self.assertIn('nejsou žádné události', r.get_data(as_text=True))

    def test_player_sets_own_status_source_player(self):
        self._login('player')
        r = self.client.post('/attendance/set', data={
            'player_id': self.player.id, 'event_key': self.ev_key,
            'status': 'going', 'range': 'upcoming'})
        self.assertEqual(r.status_code, 302)
        e = AttendanceEntry.query.filter_by(team_id=self.tid, player_id=self.player.id,
                                            event_key=self.ev_key).first()
        self.assertEqual(e.status, 'going')
        self.assertEqual(e.source, ai.SOURCE_PLAYER)
        self.assertEqual(e.updated_by_role, 'player')

    def test_coach_set_status_source_coach(self):
        self._login('coach')
        self.client.post('/attendance/set', data={
            'player_id': self.player.id, 'event_key': self.ev_key, 'status': 'maybe'})
        e = AttendanceEntry.query.filter_by(team_id=self.tid, event_key=self.ev_key).first()
        self.assertEqual(e.status, 'maybe')
        self.assertEqual(e.source, ai.SOURCE_COACH)

    def test_invalid_status_rejected(self):
        self._login('player')
        self.client.post('/attendance/set', data={
            'player_id': self.player.id, 'event_key': self.ev_key, 'status': 'bogus'})
        self.assertEqual(AttendanceEntry.query.count(), 0)

    def test_unknown_event_key_rejected(self):
        self._login('player')
        self.client.post('/attendance/set', data={
            'player_id': self.player.id, 'event_key': 'local:99999', 'status': 'going'})
        self.assertEqual(AttendanceEntry.query.count(), 0)

    def test_set_status_for_other_team_player_rejected(self):
        other = Team(name='Other')
        db.session.add(other)
        db.session.flush()
        op = Player(team_id=other.id, name='X', position='F')
        db.session.add(op)
        db.session.commit()
        self._login('coach')
        self.client.post('/attendance/set', data={
            'player_id': op.id, 'event_key': self.ev_key, 'status': 'going'})
        self.assertEqual(AttendanceEntry.query.count(), 0)

    # ---- import routes ----
    def test_import_page_coach_only(self):
        self._login('player')
        self.assertEqual(self.client.get('/attendance/import').status_code, 302)
        self._login('coach')
        self.assertEqual(self.client.get('/attendance/import').status_code, 200)

    def test_import_preview_writes_nothing(self):
        self._login('coach')
        csv = ("Jméno;14.11.2024 Trénink\nJan Novák;Ano\nNovy Hrac;Ne\n").encode('utf-8')
        before = AttendanceEntry.query.count()
        r = self.client.post('/attendance/import', data={
            'action': 'preview',
            'file': (io.BytesIO(csv), 'd.csv')},
            content_type='multipart/form-data')
        self.assertEqual(r.status_code, 200)
        self.assertIn('Náhled', r.get_data(as_text=True))
        self.assertEqual(AttendanceEntry.query.count(), before)   # no writes on preview

    def test_import_invalid_file_rejected(self):
        self._login('coach')
        r = self.client.post('/attendance/import', data={
            'action': 'preview',
            'file': (io.BytesIO(b'\x01\x02 binary'), 'x.bin')},
            content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(AttendanceEntry.query.count(), 0)

    def test_history_page_renders(self):
        self._login('coach')
        self.assertEqual(self.client.get('/attendance/import/history').status_code, 200)

    def test_owner_attendance_page(self):
        self.client.post('/owner/login', data={'owner_key': 'owner-secret'})
        self.assertEqual(self.client.get('/owner/attendance').status_code, 200)


if __name__ == '__main__':
    unittest.main()
