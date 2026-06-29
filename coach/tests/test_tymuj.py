# -*- coding: utf-8 -*-
"""First-class regression tests for the Týmuj integration (PHASE 9).

Covers parser robustness, cache lifecycle + fallback, refresh failure handling,
attendance/import/dashboard reading only from cache, the no-fetch-on-render
guarantee, the diagnostic trace and the owner debug page.
"""
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from coach.app import app
from coach.extensions import db
from coach.models import AttendanceEntry, AuditEvent, Player, Team
from coach.services import tymuj as tymuj_svc


# Rich ICS: practice + game + cancelled + recurring + duplicate + malformed.
ICS_RICH = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:1@t
DTSTART:20260701T173000
DTEND:20260701T190000
SUMMARY:Trénink mládeže
LOCATION:Zimní stadion
ATTENDEE;CN=Jan Novák:mailto:jan@x.cz
ATTENDEE;CN="Petr Svoboda":mailto:petr@x.cz
END:VEVENT
BEGIN:VEVENT
UID:2@t
DTSTART:20260703T180000
SUMMARY:Zápas s HC Soupeř
ATTENDEE;CN=Jan Novák:mailto:jan@x.cz
END:VEVENT
BEGIN:VEVENT
UID:3@t
DTSTART:20260705T100000
SUMMARY:Trénink zrušený
STATUS:CANCELLED
END:VEVENT
BEGIN:VEVENT
UID:4@t
DTSTART:20260707T173000
RRULE:FREQ=WEEKLY;COUNT=5
SUMMARY:Pravidelný trénink
END:VEVENT
BEGIN:VEVENT
UID:1@t
DTSTART:20260701T173000
SUMMARY:Trénink mládeže
END:VEVENT
BEGIN:VEVENT
DTSTART:20260709T173000
END:VEVENT
END:VCALENDAR
"""


def _meta(url='http://feed.test/c.ics'):
    return {'status': 200, 'content_type': 'text/calendar', 'bytes': len(ICS_RICH),
            'encoding': 'utf-8', 'final_url': url, 'redirected': False}


# --------------------------------------------------------------------------
# Parser (pure, no DB)
# --------------------------------------------------------------------------
class TymujParserTest(unittest.TestCase):
    def test_parse_counts(self):
        out = tymuj_svc.parse_ics(ICS_RICH)
        st = out['stats']
        self.assertEqual(st['event_count'], 4)          # duplicate + malformed dropped
        self.assertEqual(st['practice_count'], 2)       # cancelled practice excluded
        self.assertEqual(st['game_count'], 1)
        self.assertEqual(st['cancelled_count'], 1)
        self.assertEqual(st['recurring_count'], 1)
        self.assertEqual(st['participant_count'], 2)

    def test_game_vs_practice_classification(self):
        events = {e['uid']: e for e in tymuj_svc.parse_ics(ICS_RICH)['events']}
        self.assertEqual(events['2@t']['kind'], 'match')
        self.assertEqual(events['1@t']['kind'], 'training')

    def test_diacritics_and_fields(self):
        events = {e['uid']: e for e in tymuj_svc.parse_ics(ICS_RICH)['events']}
        e1 = events['1@t']
        self.assertEqual(e1['title'], 'Trénink mládeže')
        self.assertEqual(e1['location'], 'Zimní stadion')
        self.assertEqual(e1['time'], '17:30')
        self.assertEqual(e1['end_time'], '19:00')

    def test_participants_sorted_and_quoted_cn(self):
        self.assertEqual(tymuj_svc.parse_ics(ICS_RICH)['participants'],
                         ['Jan Novák', 'Petr Svoboda'])

    def test_empty_calendar(self):
        out = tymuj_svc.parse_ics('BEGIN:VCALENDAR\nEND:VCALENDAR\n')
        self.assertEqual(out['events'], [])
        self.assertEqual(out['stats']['event_count'], 0)

    def test_malformed_never_crashes(self):
        for junk in ('', 'not an ics', 'BEGIN:VEVENT\nDTSTART:garbage\nEND:VEVENT',
                     'BEGIN:VEVENT\nSUMMARY:no start\nEND:VEVENT'):
            out = tymuj_svc.parse_ics(junk)
            self.assertEqual(out['events'], [])

    def test_windows1250_decoding(self):
        raw = ICS_RICH.encode('cp1250')
        text, enc = tymuj_svc._decode_ics(raw, 'text/calendar; charset=windows-1250')
        self.assertIn('Trénink mládeže', text)
        self.assertEqual(enc.lower().replace('-', ''), 'windows1250')


# --------------------------------------------------------------------------
# Cache lifecycle / refresh / fallback (DB :memory:)
# --------------------------------------------------------------------------
class TymujCacheTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
                          ADMIN_SECRET_KEY='owner-secret')
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.team = Team(name='HC Test', tymuj_ics_url='http://feed.test/c.ics')
        db.session.add(self.team)
        db.session.commit()
        self.tid = self.team.id
        db.session.add(Player(team_id=self.tid, name='Jan Novák', position='F'))
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _login(self, role='coach'):
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid
            s['team_role'] = role
            s['team_login'] = True

    def test_refresh_success_writes_cache(self):
        with patch.object(tymuj_svc, '_fetch_ics_with_meta', return_value=(ICS_RICH, _meta())):
            ok, _msg = tymuj_svc.refresh_cache(self.tid, self.team.tymuj_ics_url)
        self.assertTrue(ok)
        status = tymuj_svc.get_status(self.tid)
        self.assertEqual(status['events_count'], 4)
        self.assertEqual(status['stats']['game_count'], 1)
        self.assertIsNotNone(status['last_success'])
        self.assertIsNone(status['last_error'])
        self.assertFalse(status['stale'])

    def test_invalid_url_refresh_fails(self):
        ok, _msg = tymuj_svc.refresh_cache(self.tid, 'http://127.0.0.1/c.ics')
        self.assertFalse(ok)

    def test_failure_keeps_last_good_cache(self):
        with patch.object(tymuj_svc, '_fetch_ics_with_meta', return_value=(ICS_RICH, _meta())):
            tymuj_svc.refresh_cache(self.tid, self.team.tymuj_ics_url)
        with patch.object(tymuj_svc, '_fetch_ics_with_meta', side_effect=TimeoutError('boom')):
            ok, msg = tymuj_svc.refresh_cache(self.tid, self.team.tymuj_ics_url)
        self.assertFalse(ok)
        self.assertEqual(msg, tymuj_svc.FAIL_MESSAGE)
        status = tymuj_svc.get_status(self.tid)
        self.assertEqual(status['events_count'], 4)          # preserved
        self.assertIsNotNone(status['last_error'])
        self.assertIsNotNone(status['last_failure'])
        self.assertIsNotNone(AuditEvent.query.filter_by(
            event='integration.tymuj.failure', team_id=self.tid).first())

    def test_stale_flag(self):
        old = (date.today()).isoformat()  # placeholder, override below
        with patch.object(tymuj_svc, '_fetch_ics_with_meta', return_value=(ICS_RICH, _meta())):
            tymuj_svc.refresh_cache(self.tid, self.team.tymuj_ics_url)
        # hand-age the cache far into the past
        payload = tymuj_svc._load_cache_payload(self.tid)
        payload['last_success'] = '2000-01-01T00:00:00'
        payload['updated_at'] = '2000-01-01T00:00:00'
        tymuj_svc._write_cache(self.tid, payload)
        self.assertTrue(tymuj_svc.get_status(self.tid)['stale'])

    def test_attendance_reads_cache_excludes_cancelled(self):
        with patch.object(tymuj_svc, '_fetch_ics_with_meta', return_value=(ICS_RICH, _meta())):
            tymuj_svc.refresh_cache(self.tid, self.team.tymuj_ics_url)
        evs = tymuj_svc.get_cached_events(self.tid, date(2026, 6, 1), date(2026, 12, 31))
        self.assertEqual(len(evs), 3)                         # cancelled excluded
        self.assertTrue(all(not e['cancelled'] for e in evs))
        evs_all = tymuj_svc.get_cached_events(self.tid, date(2026, 6, 1), date(2026, 12, 31),
                                              include_cancelled=True)
        self.assertEqual(len(evs_all), 4)

    def test_import_reads_cache(self):
        with patch.object(tymuj_svc, '_fetch_ics_with_meta', return_value=(ICS_RICH, _meta())):
            tymuj_svc.refresh_cache(self.tid, self.team.tymuj_ics_url)
        self.assertEqual(tymuj_svc.get_cached_participants(self.tid),
                         ['Jan Novák', 'Petr Svoboda'])

    def test_get_pages_never_fetch(self):
        with patch.object(tymuj_svc, '_fetch_ics_with_meta', return_value=(ICS_RICH, _meta())):
            tymuj_svc.refresh_cache(self.tid, self.team.tymuj_ics_url)
        self._login('coach')
        with patch.object(tymuj_svc, 'safe_urlopen') as opener:
            self.assertEqual(self.client.get('/app?year=2026&month=7').status_code, 200)
            self.assertEqual(self.client.get('/dochazka').status_code, 200)
            self.assertEqual(self.client.get('/players/import/tymuj').status_code, 200)
            self.assertFalse(opener.called)

    def test_diagnostic_trace_has_all_steps(self):
        with patch.object(tymuj_svc, 'validate_public_http_url', return_value=(True, '')), \
             patch.object(tymuj_svc, '_fetch_ics_with_meta', return_value=(ICS_RICH, _meta())):
            ok, msg, trace = tymuj_svc.diagnostic_refresh(self.tid)
        self.assertTrue(ok, msg)
        steps = [s['step'] for s in trace]
        for expected in ('URL loaded', 'URL validation', 'HTTP request', 'Response status',
                         'Download size', 'Encoding', 'Parser', 'Events parsed',
                         'Practices parsed', 'Games parsed', 'Cancelled parsed',
                         'Recurring parsed', 'Players detected', 'Cache validation',
                         'Cache write', 'Attendance mapping', 'Dashboard model', 'Import model'):
            self.assertIn(expected, steps)
        self.assertTrue(all(s['ok'] for s in trace))

    def test_diagnostic_failure_trace(self):
        with patch.object(tymuj_svc, 'validate_public_http_url', return_value=(True, '')), \
             patch.object(tymuj_svc, '_fetch_ics_with_meta', side_effect=TimeoutError('down')):
            ok, _msg, trace = tymuj_svc.diagnostic_refresh(self.tid)
        self.assertFalse(ok)
        self.assertEqual(trace[-1]['step'], 'pipeline failure')

    def test_owner_tymuj_debug_page(self):
        with patch.object(tymuj_svc, '_fetch_ics_with_meta', return_value=(ICS_RICH, _meta())):
            tymuj_svc.refresh_cache(self.tid, self.team.tymuj_ics_url)
        self.client.post('/owner/login', data={'owner_key': 'owner-secret'})
        res = self.client.get('/owner/tymuj-debug')
        self.assertEqual(res.status_code, 200)
        self.assertIn('Týmuj', res.get_data(as_text=True))


class _FakeResp:
    """Minimal urllib-response stand-in for safe_urlopen patches."""
    def __init__(self, body=b'', status=200, headers=None, raise_on_read=None):
        self._body = body
        self.status = status
        self.headers = headers or {'Content-Type': 'text/calendar; charset=utf-8',
                                   'Content-Length': str(len(body)), 'Server': 'nginx'}
        self._raise = raise_on_read

    def read(self, n=-1):
        if self._raise:
            raise self._raise
        return self._body if (n is None or n < 0) else self._body[:n]

    def geturl(self):
        return 'http://feed.test/c.ics'

    def close(self):
        pass


class TymujFetchReliabilityTest(unittest.TestCase):
    """Exercises the real fetch path (_fetch_once/_fetch_ics_with_meta via
    patched safe_urlopen): timeout classification + single read-timeout retry."""

    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.team = Team(name='HC Test', tymuj_ics_url='http://feed.test/c.ics')
        db.session.add(self.team)
        db.session.commit()
        self.tid = self.team.id
        # validate is patched True for all tests (fake host); backoff disabled.
        self._p_validate = patch.object(tymuj_svc, 'validate_public_http_url', return_value=(True, ''))
        self._p_backoff = patch.object(tymuj_svc, 'RETRY_BACKOFF', 0)
        self._p_validate.start()
        self._p_backoff.start()

    def tearDown(self):
        self._p_validate.stop()
        self._p_backoff.stop()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _body(self):
        return ICS_RICH.encode('utf-8')

    def test_slow_response_succeeds_single_attempt(self):
        with patch.object(tymuj_svc, 'safe_urlopen', return_value=_FakeResp(self._body())):
            ok, _msg = tymuj_svc.refresh_cache(self.tid, self.team.tymuj_ics_url)
        self.assertTrue(ok)
        st = tymuj_svc.get_status(self.tid)
        self.assertGreater(st['events_count'], 0)
        self.assertFalse(st['http'].get('retry_attempted'))

    def test_read_timeout_then_retry_succeeds(self):
        seq = [_FakeResp(raise_on_read=TimeoutError('The read operation timed out')),
               _FakeResp(self._body())]
        with patch.object(tymuj_svc, 'safe_urlopen', side_effect=seq):
            ok, _msg = tymuj_svc.refresh_cache(self.tid, self.team.tymuj_ics_url)
        self.assertTrue(ok)
        st = tymuj_svc.get_status(self.tid)
        self.assertGreater(st['events_count'], 0)
        self.assertTrue(st['http'].get('retry_attempted'))

    def test_read_timeout_then_retry_fails(self):
        seq = [_FakeResp(raise_on_read=TimeoutError('The read operation timed out')),
               _FakeResp(raise_on_read=TimeoutError('The read operation timed out'))]
        with patch.object(tymuj_svc, 'safe_urlopen', side_effect=seq):
            ok, msg = tymuj_svc.refresh_cache(self.tid, self.team.tymuj_ics_url)
        self.assertFalse(ok)
        self.assertEqual(msg, tymuj_svc.FAIL_MESSAGE)
        st = tymuj_svc.get_status(self.tid)
        self.assertEqual(st['last_error_code'], 'read_timeout')
        self.assertTrue(st['last_http'].get('retry_attempted'))

    def test_connect_timeout_classified_and_not_retried(self):
        opener = patch.object(tymuj_svc, 'safe_urlopen', side_effect=TimeoutError('timed out'))
        with opener as m:
            ok, _msg = tymuj_svc.refresh_cache(self.tid, self.team.tymuj_ics_url)
        self.assertFalse(ok)
        self.assertEqual(m.call_count, 1)          # connect timeout is NOT retried
        self.assertEqual(tymuj_svc.get_status(self.tid)['last_error_code'], 'connect_timeout')

    def test_read_timeout_does_not_overwrite_good_cache(self):
        with patch.object(tymuj_svc, 'safe_urlopen', return_value=_FakeResp(self._body())):
            tymuj_svc.refresh_cache(self.tid, self.team.tymuj_ics_url)
        good = tymuj_svc.get_status(self.tid)['events_count']
        self.assertGreater(good, 0)
        seq = [_FakeResp(raise_on_read=TimeoutError('rt')),
               _FakeResp(raise_on_read=TimeoutError('rt'))]
        with patch.object(tymuj_svc, 'safe_urlopen', side_effect=seq):
            ok, _msg = tymuj_svc.refresh_cache(self.tid, self.team.tymuj_ics_url)
        self.assertFalse(ok)
        st = tymuj_svc.get_status(self.tid)
        self.assertEqual(st['events_count'], good)     # preserved, not emptied
        self.assertIsNotNone(st['last_error'])

    def test_oversized_rejected_in_fetch_path(self):
        big = b'x' * (2048)
        with patch.object(tymuj_svc, 'MAX_BYTES', 1024), \
             patch.object(tymuj_svc, 'safe_urlopen', return_value=_FakeResp(big)):
            ok, _msg = tymuj_svc.refresh_cache(self.tid, self.team.tymuj_ics_url)
        self.assertFalse(ok)
        self.assertEqual(tymuj_svc.get_status(self.tid)['last_error_code'], 'too_large')

    def test_headers_captured_in_diagnostic_trace(self):
        with patch.object(tymuj_svc, 'safe_urlopen', return_value=_FakeResp(self._body())):
            ok, _msg, trace = tymuj_svc.diagnostic_refresh(self.tid)
        self.assertTrue(ok)
        resp_step = next(s for s in trace if s['step'] == 'Response status')
        self.assertIn('Content-Type', resp_step.get('headers') or {})
        http_step = next(s for s in trace if s['step'] == 'HTTP request')
        self.assertEqual(http_step.get('timeout'), tymuj_svc.TIMEOUT)

    def test_read_timeout_failure_trace_is_specific(self):
        seq = [_FakeResp(raise_on_read=TimeoutError('rt')),
               _FakeResp(raise_on_read=TimeoutError('rt'))]
        with patch.object(tymuj_svc, 'safe_urlopen', side_effect=seq):
            ok, _msg, trace = tymuj_svc.diagnostic_refresh(self.tid)
        self.assertFalse(ok)
        fail = trace[-1]
        self.assertEqual(fail['step'], 'pipeline failure')
        self.assertEqual(fail['reason'], 'read_timeout')
        self.assertTrue(fail['retry_attempted'])

    def test_url_token_is_masked(self):
        masked = tymuj_svc._mask_url('https://api2.tymuj.cz/event/calendar/SECRETTOKEN123.ics')
        self.assertNotIn('SECRETTOKEN123', masked)
        self.assertIn('api2.tymuj.cz', masked)
        self.assertIn('.ics', masked)


if __name__ == '__main__':
    unittest.main()
