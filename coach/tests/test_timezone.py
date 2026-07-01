# -*- coding: utf-8 -*-
"""Prague display timezone (DST-safe). DB stores naive UTC; display = Europe/Prague."""
import unittest
from datetime import datetime, timezone

from coach.app import app


class PragueFilterTest(unittest.TestCase):
    def setUp(self):
        self.f = app.jinja_env.filters['prague']

    def test_summer_utc_plus_2(self):
        # 2026-07-01 12:00 UTC -> 14:00 Prague (CEST, UTC+2)
        self.assertEqual(self.f(datetime(2026, 7, 1, 12, 0), '%H:%M'), '14:00')

    def test_winter_utc_plus_1(self):
        # 2026-01-01 12:00 UTC -> 13:00 Prague (CET, UTC+1)
        self.assertEqual(self.f(datetime(2026, 1, 1, 12, 0), '%H:%M'), '13:00')

    def test_dst_boundary(self):
        # DST starts 2026-03-29 01:00 UTC -> 03:00 Prague (spring forward)
        self.assertEqual(self.f(datetime(2026, 3, 29, 1, 30), '%H:%M'), '03:30')

    def test_none_is_empty(self):
        self.assertEqual(self.f(None), '')

    def test_naive_treated_as_utc(self):
        # a naive datetime is assumed UTC (storage convention)
        self.assertEqual(self.f(datetime(2026, 7, 1, 0, 0), '%d.%m. %H:%M'), '01.07. 02:00')

    def test_aware_datetime_respected(self):
        # already-aware UTC datetime converts the same way
        self.assertEqual(self.f(datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc), '%H:%M'), '14:00')

    def test_now_prague_global_present(self):
        self.assertIn('now_prague', app.jinja_env.globals)


if __name__ == '__main__':
    unittest.main()
