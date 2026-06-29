# -*- coding: utf-8 -*-
"""Attendance export (CSV long + matrix) and edge-case coverage."""
import unittest
from datetime import date, timedelta

from coach.app import app
from coach.extensions import db
from coach.models import AttendanceEntry, Player, Team, TeamKey, TrainingEvent
from coach.services.keys import hash_team_key


class ExportTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='T'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        db.session.add(TeamKey(team_id=self.tid, role='player', key_hash=hash_team_key('pk')))
        self.p1 = Player(team_id=self.tid, name='Jan Novák', position='F')
        self.p2 = Player(team_id=self.tid, name='Petr Brankář', position='G')
        db.session.add_all([self.p1, self.p2]); db.session.flush()
        today = date.today()
        self.e_future = TrainingEvent(team_id=self.tid, day=today + timedelta(days=5),
                                      time='18:00', title='Future Trénink', kind='training')
        self.e_past = TrainingEvent(team_id=self.tid, day=today - timedelta(days=5),
                                    time='10:00', title='Past Zápas', kind='match')
        db.session.add_all([self.e_future, self.e_past]); db.session.flush()
        db.session.add(AttendanceEntry(team_id=self.tid, player_id=self.p1.id,
                                       event_key='local:%d' % self.e_future.id, status='going',
                                       event_day=self.e_future.day, source='coachhub_coach'))
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _coach(self):
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid; s['team_role'] = 'coach'; s['team_login'] = True

    def _player(self):
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid; s['team_role'] = 'player'; s['team_login'] = True

    def test_export_is_coach_only(self):
        self._player()
        r = self.client.get('/attendance/export?format=long&range=all')
        self.assertEqual(r.status_code, 302)

    def test_long_export_headers_and_content(self):
        self._coach()
        r = self.client.get('/attendance/export?format=long&range=all')
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/csv', r.mimetype if hasattr(r, 'mimetype') else r.content_type)
        self.assertIn('attachment', r.headers.get('Content-Disposition', ''))
        text = r.get_data(as_text=True)
        self.assertTrue(text.startswith('﻿'))          # Excel BOM
        self.assertIn('Hráč;Pozice;Datum;Čas;Typ;Událost;Stav;Zdroj;Aktualizováno', text)
        self.assertIn('Jan Novák;F;', text)
        self.assertIn('Jdu', text)                          # status label
        self.assertIn('CoachHub Coach', text)               # source label

    def test_long_export_respects_range(self):
        self._coach()
        fut = self.client.get('/attendance/export?format=long&range=future').get_data(as_text=True)
        self.assertIn('Future Trénink', fut)
        self.assertNotIn('Past Zápas', fut)
        past = self.client.get('/attendance/export?format=long&range=past').get_data(as_text=True)
        self.assertIn('Past Zápas', past)
        self.assertNotIn('Future Trénink', past)

    def test_long_export_respects_event_type(self):
        self._coach()
        only_matches = self.client.get('/attendance/export?format=long&range=all&etype=match').get_data(as_text=True)
        self.assertIn('Past Zápas', only_matches)
        self.assertNotIn('Future Trénink', only_matches)

    def test_matrix_export(self):
        self._coach()
        text = self.client.get('/attendance/export?format=matrix&range=all').get_data(as_text=True)
        self.assertIn('Hráč;Pozice;', text)
        self.assertIn('Future Trénink', text)               # event as a column header
        self.assertIn('Jan Novák;F;', text)
        # Jan is 'going' on the future event -> a 'Jdu' cell exists
        self.assertIn('Jdu', text)

    def test_legacy_range_value_in_export(self):
        self._coach()
        r = self.client.get('/attendance/export?format=long&range=season')   # -> all
        self.assertEqual(r.status_code, 200)


class EdgeCaseTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='T'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        self.client = app.test_client()
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid; s['team_role'] = 'coach'; s['team_login'] = True

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def test_no_players_no_events(self):
        self.assertEqual(self.client.get('/dochazka').status_code, 200)
        self.assertEqual(self.client.get('/attendance/export?format=long&range=all').status_code, 200)
        self.assertEqual(self.client.get('/attendance/export?format=matrix&range=all').status_code, 200)

    def test_duplicate_player_names(self):
        for _ in range(2):
            db.session.add(Player(team_id=self.tid, name='Jan Novák', position='F'))
        db.session.add(TrainingEvent(team_id=self.tid, day=date.today() + timedelta(days=2),
                                     time='18:00', title='T', kind='training'))
        db.session.commit()
        r = self.client.get('/dochazka')
        self.assertEqual(r.status_code, 200)
        # both same-named players present as distinct rows (one name cell each)
        self.assertEqual(r.get_data(as_text=True).count('class="am-lcell"'), 2)
        exp = self.client.get('/attendance/export?format=matrix&range=future').get_data(as_text=True)
        self.assertEqual(exp.count('Jan Novák;F'), 2)

    def test_entry_for_deleted_event_is_ignored(self):
        p = Player(team_id=self.tid, name='Jan', position='F'); db.session.add(p); db.session.flush()
        # attendance entry pointing at an event_key that no longer exists
        db.session.add(AttendanceEntry(team_id=self.tid, player_id=p.id, event_key='local:99999',
                                       status='going', event_day=date.today(), source='coachhub_coach'))
        db.session.commit()
        self.assertEqual(self.client.get('/dochazka?range=all').status_code, 200)
        exp = self.client.get('/attendance/export?format=long&range=all').get_data(as_text=True)
        # no current event -> only the header row, the orphan entry does not appear
        self.assertNotIn('local:99999', exp)

    def test_only_future_then_only_past(self):
        p = Player(team_id=self.tid, name='A', position='F'); db.session.add(p)
        db.session.add(TrainingEvent(team_id=self.tid, day=date.today() + timedelta(days=3),
                                     time='9:00', title='Fut', kind='training'))
        db.session.commit()
        self.assertEqual(self.client.get('/dochazka?range=future').status_code, 200)
        # past filter -> no events, page still renders (empty state)
        r = self.client.get('/dochazka?range=past')
        self.assertEqual(r.status_code, 200)
        self.assertIn('Žádné události', r.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
