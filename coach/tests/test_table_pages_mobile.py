# -*- coding: utf-8 -*-
"""Table & import pages batch — mobile table-to-card layers for Attendance Import,
Attendance Import History, Audit Log, and Týmuj Player Import. Verifies each
mobile layer renders, coach-only access + team isolation are preserved, desktop
table markup remains, CSRF is present, and no filesystem paths leak.
"""
import unittest
from datetime import datetime, timedelta

from coach.app import app
from coach.extensions import db
from coach.models import AttendanceImport, AuditEvent, Team, TeamKey
from coach.services.keys import hash_team_key


class _Fixture(unittest.TestCase):
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

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self, role='coach', tid=None):
        with self.client.session_transaction() as s:
            s['team_id'] = tid or self.tid; s['team_role'] = role; s['team_login'] = True


class AttendanceImportMobileTest(_Fixture):
    def test_renders_upload_stage_with_mobile_layer(self):
        self._login('coach')
        r = self.client.get('/attendance/import')
        self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        self.assertIn('aim-bar', h)
        self.assertIn('name="file"', h)                 # desktop upload form present
        self.assertIn('enctype="multipart/form-data"', h)
        self.assertIn('value="preview"', h)             # existing action field
        self.assertIn('csrf_token', h)

    def test_player_blocked(self):
        self._login('player')
        self.assertEqual(self.client.get('/attendance/import').status_code, 302)


class ImportHistoryMobileTest(_Fixture):
    def setUp(self):
        super().setUp()
        db.session.add(AttendanceImport(team_id=self.tid, source='tymuj', file_type='csv',
                                        filename='dochazka_2025.csv', players_created=3, events_created=2,
                                        attendance_imported=20, skipped=1, overwritten=0, status='done',
                                        created_at=datetime.utcnow()))
        db.session.add(AttendanceImport(team_id=self.other.id, source='tymuj', file_type='csv',
                                        filename='cizi_soubor.csv', status='done', created_at=datetime.utcnow()))
        db.session.commit()

    def test_renders_mobile_layer_team_scoped_no_paths(self):
        self._login('coach')
        r = self.client.get('/attendance/import/history')
        self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        self.assertIn('aihm-bar', h)
        self.assertIn('dochazka_2025.csv', h)           # our batch
        self.assertNotIn('cizi_soubor.csv', h)          # other team excluded
        self.assertIn('<table', h)                      # desktop table remains
        self.assertNotIn('/home/', h)                   # no filesystem path
        self.assertNotIn('protected_exports', h)

    def test_player_blocked(self):
        self._login('player')
        self.assertEqual(self.client.get('/attendance/import/history').status_code, 302)


class AuditLogMobileTest(_Fixture):
    def setUp(self):
        super().setUp()
        db.session.add(AuditEvent(event='team.login', team_id=self.tid, role='coach', ip_truncated='1.2.3.x', meta='{"ok":1}'))
        db.session.add(AuditEvent(event='secret.other_team', team_id=self.other.id, role='coach', ip_truncated='9.9.9.x'))
        db.session.commit()

    def test_renders_mobile_layer_team_scoped(self):
        self._login('coach')
        r = self.client.get('/admin/audit-log')
        self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        self.assertIn('alm-bar', h)
        self.assertIn('team.login', h)                  # our event
        self.assertNotIn('secret.other_team', h)        # other team excluded
        self.assertIn('id="auditTable"', h)             # desktop table remains
        self.assertIn('id="auditSearch"', h)            # filter preserved

    def test_player_blocked(self):
        self._login('player')
        self.assertEqual(self.client.get('/admin/audit-log').status_code, 302)


class TymujImportMobileTest(_Fixture):
    def setUp(self):
        super().setUp()
        # ICS URL required to reach the page; no cache -> empty-state renders (200).
        self.team.tymuj_ics_url = 'https://tymuj.example/calendar/x.ics'
        db.session.commit()

    def test_renders_mobile_layer(self):
        self._login('coach')
        r = self.client.get('/players/import/tymuj')
        self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        self.assertIn('tpm-bar', h)
        self.assertIn('refresh_tymuj', h)               # existing refresh form preserved
        self.assertIn('csrf_token', h)

    def test_player_blocked(self):
        self._login('player')
        self.assertEqual(self.client.get('/players/import/tymuj').status_code, 302)


if __name__ == '__main__':
    unittest.main()
