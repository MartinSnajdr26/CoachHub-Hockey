# -*- coding: utf-8 -*-
"""Pure-helper tests for the calendar export module (team .ics feed building)."""
import unittest
from datetime import date, timedelta

from coach.services import calendar_export as ce


class CalendarExportUnitTest(unittest.TestCase):
    def test_duration_rules(self):
        self.assertEqual(ce.duration_minutes('training'), 75)
        self.assertEqual(ce.duration_minutes('Trénink'), 75)
        self.assertEqual(ce.duration_minutes('match'), 180)
        self.assertEqual(ce.duration_minutes('Zápas'), 180)
        self.assertEqual(ce.duration_minutes('camp'), 90)
        self.assertEqual(ce.duration_minutes(None), 90)
        self.assertEqual(ce.duration_minutes(''), 90)

    def test_start_end_training_75(self):
        s, e, all_day = ce.start_end(date(2026, 7, 18), '18:00', 'training')
        self.assertFalse(all_day)
        self.assertEqual((e - s), timedelta(minutes=75))
        # 18:00 Prague (July, UTC+2) -> 16:00Z, +75 -> 17:15Z
        self.assertEqual(ce._fmt_utc(s), '20260718T160000Z')
        self.assertEqual(ce._fmt_utc(e), '20260718T171500Z')

    def test_start_end_match_180(self):
        s, e, _ = ce.start_end(date(2026, 7, 18), '16:00', 'match')
        self.assertEqual((e - s), timedelta(minutes=180))

    def test_start_end_unknown_90(self):
        s, e, _ = ce.start_end(date(2026, 7, 18), '17:00', 'gala')
        self.assertEqual((e - s), timedelta(minutes=90))

    def test_missing_time_is_all_day(self):
        s, e, all_day = ce.start_end(date(2026, 7, 18), '', 'training')
        self.assertTrue(all_day)
        self.assertEqual(s, date(2026, 7, 18))
        self.assertEqual(e, date(2026, 7, 19))

    def test_ics_escaping(self):
        self.assertEqual(ce.ics_escape('A; B, C\\D\nE'), 'A\\; B\\, C\\\\D\\nE')

    def test_build_feed_multiple_vevents_and_alarm(self):
        evs = [
            {'id': 1, 'title': 'Trénink A', 'kind': 'training', 'day': date(2026, 7, 18), 'time': '18:00'},
            {'id': 2, 'title': 'Zápas B', 'kind': 'match', 'day': date(2026, 7, 20), 'time': '16:00'},
        ]
        ics = ce.build_feed(evs, 'https://h/attendance')
        self.assertTrue(ics.startswith('BEGIN:VCALENDAR'))
        self.assertEqual(ics.count('BEGIN:VEVENT'), 2)
        self.assertEqual(ics.count('END:VEVENT'), 2)
        self.assertEqual(ics.count('BEGIN:VALARM'), 2)
        self.assertEqual(ics.count('TRIGGER:-P1D'), 2)
        # stable UID per event id, on the fixed domain (not request host)
        self.assertIn('UID:coachhub-event-1@coachhubhockey.com', ics)
        self.assertIn('UID:coachhub-event-2@coachhubhockey.com', ics)
        self.assertIn('DTSTART:20260718T160000Z', ics)
        self.assertIn('DTEND:20260718T171500Z', ics)          # training +75
        self.assertIn('DTEND:20260720T170000Z', ics)          # match 16->19 = 14:00Z..17:00Z
        self.assertIn('https://h/attendance', ics)
        self.assertTrue(ics.endswith('END:VCALENDAR\r\n'))

    def test_empty_feed_is_valid(self):
        ics = ce.build_feed([], 'https://h/attendance')
        self.assertIn('BEGIN:VCALENDAR', ics)
        self.assertIn('END:VCALENDAR', ics)
        self.assertNotIn('BEGIN:VEVENT', ics)


if __name__ == '__main__':
    unittest.main()
