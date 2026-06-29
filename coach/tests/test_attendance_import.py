# -*- coding: utf-8 -*-
"""Regression tests for CoachHub-first attendance: Týmuj CSV/Excel import."""
import io
import unittest
import zipfile

from coach.app import app
from coach.extensions import db
from coach.models import AttendanceEntry, AttendanceImport, Player, TrainingEvent
from coach.services import attendance_import as ai


CSV_MATRIX = (
    "Jméno;14.11.2024 18:00 Trénink;16.11.2024 10:00 Zápas\n"
    "Jan Novák;Ano;Ne\n"
    "Petr Svoboda;?;Možná\n"
    "Celkem;1;0\n"
)


def _xlsx(grid):
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rows = []
    for r, row in enumerate(grid, start=1):
        cells = []
        for c, val in enumerate(row):
            ref = '%s%d' % (chr(65 + c), r)
            esc = (str(val).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
            cells.append('<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (ref, esc))
        rows.append('<row r="%d">%s</row>' % (r, ''.join(cells)))
    sheet = ('<?xml version="1.0" encoding="UTF-8"?>'
             '<worksheet xmlns="%s"><sheetData>%s</sheetData></worksheet>' % (ns, ''.join(rows)))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('xl/worksheets/sheet1.xml', sheet)
    return buf.getvalue()


class ParserTest(unittest.TestCase):
    def test_csv_matrix_parses(self):
        p = ai.parse_attendance_file('a.csv', CSV_MATRIX.encode('utf-8'))
        self.assertEqual(p['file_type'], 'csv')
        self.assertEqual(len(p['events']), 2)
        self.assertEqual([e['date'] for e in p['events']], ['2024-11-14', '2024-11-16'])
        self.assertEqual(p['events'][1]['time'], '10:00')
        names = sorted(pl['name'] for pl in p['players'])
        self.assertEqual(names, ['Jan Novák', 'Petr Svoboda'])   # 'Celkem' total row dropped
        # Jan: going + not_going ; Petr: maybe (?-> unknown skipped)
        st = {(c['p'], c['e']): c['status'] for c in p['cells']}
        self.assertEqual(st[(0, 0)], 'going')
        self.assertEqual(st[(0, 1)], 'not_going')
        self.assertEqual(st[(1, 1)], 'maybe')
        self.assertNotIn((1, 0), st)                              # '?' -> unknown, not written

    def test_status_mapping(self):
        for raw, exp in [('Ano', 'going'), ('ANO', 'going'), ('Ne', 'not_going'),
                         ('Možná', 'maybe'), ('?', 'unknown'), ('', 'unknown'),
                         ('✓', 'going'), ('✗', 'not_going'), ('yes', 'going')]:
            self.assertEqual(ai.map_status(raw), exp, raw)

    def test_formula_and_email_and_phone_ignored(self):
        self.assertEqual(ai._sanitize_cell('=cmd|/c calc'), 'cmd|/c calc')   # no leading =
        self.assertEqual(ai._sanitize_cell('jan@example.com'), '')
        self.assertEqual(ai._sanitize_cell('+420 777 123 456'), '')
        # an event row whose values are emails -> all unknown, nothing imported
        csv = "Jméno;14.11.2024 Trénink\nJan;=1+1\n"
        p = ai.parse_attendance_file('x.csv', csv.encode())
        self.assertEqual(p['cells'], [])

    def test_empty_and_garbage(self):
        with self.assertRaises(ai.AttendanceImportError):
            ai.parse_attendance_file('e.csv', b'')
        with self.assertRaises(ai.AttendanceImportError):
            ai.parse_attendance_file('e.bin', b'\x01\x02\x03 not a sheet')

    def test_oversized_rejected(self):
        big = b'a,b\n' * (ai.MAX_FILE_BYTES)
        with self.assertRaises(ai.AttendanceImportError):
            ai.parse_attendance_file('big.csv', big[:ai.MAX_FILE_BYTES + 10])

    def test_xlsx_parses(self):
        grid = [['Jméno', '14.11.2024 Trénink', '16.11.2024 Zápas'],
                ['Jan Novák', 'Ano', 'Ne'],
                ['Petr Svoboda', 'Ne', 'Ano']]
        p = ai.parse_attendance_file('a.xlsx', _xlsx(grid))
        self.assertEqual(p['file_type'], 'xlsx')
        self.assertEqual(len(p['events']), 2)
        self.assertEqual(len(p['players']), 2)
        self.assertEqual(len(p['cells']), 4)


class PreviewConfirmTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        from coach.models import Team
        self.team = Team(name='HC Test')
        db.session.add(self.team)
        db.session.commit()
        self.tid = self.team.id
        db.session.add(Player(team_id=self.tid, name='Jan Novák', position='F'))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _decisions(self, preview):
        return ({str(p['idx']): p['default_action'] for p in preview['players']},
                {str(e['idx']): e['default_action'] for e in preview['events']})

    def test_preview_writes_nothing(self):
        p = ai.parse_attendance_file('a.csv', CSV_MATRIX.encode())
        before = AttendanceEntry.query.count()
        prev = ai.build_import_preview(self.tid, p)
        self.assertEqual(AttendanceEntry.query.count(), before)
        self.assertEqual(Player.query.count(), 1)
        # Jan matched existing, Petr new; events new
        kinds = {pl['name']: pl['kind'] for pl in prev['players']}
        self.assertEqual(kinds['Jan Novák'], 'exists')
        self.assertEqual(kinds['Petr Svoboda'], 'new')
        self.assertEqual(prev['summary']['events_new'], 2)

    def test_confirm_creates_and_imports(self):
        p = ai.parse_attendance_file('a.csv', CSV_MATRIX.encode())
        prev = ai.build_import_preview(self.tid, p)
        pdec, edec = self._decisions(prev)
        batch = ai.confirm_import(self.tid, p, pdec, edec, role='coach')
        self.assertEqual(batch.players_created, 1)        # Petr; Jan merged
        self.assertEqual(batch.events_created, 2)
        self.assertEqual(batch.attendance_imported, 3)    # Jan g/ng + Petr maybe
        self.assertEqual(Player.query.count(), 2)
        rows = AttendanceEntry.query.all()
        self.assertTrue(all(r.source == ai.SOURCE_IMPORT for r in rows))
        self.assertTrue(all(r.source_detail == str(batch.id) for r in rows))

    def test_reimport_skips_by_default_overwrites_when_requested(self):
        p = ai.parse_attendance_file('a.csv', CSV_MATRIX.encode())
        prev = ai.build_import_preview(self.tid, p)
        pdec, edec = self._decisions(prev)
        ai.confirm_import(self.tid, p, pdec, edec, role='coach')
        # re-preview so events now match the just-created local events (use:)
        p2 = ai.parse_attendance_file('a.csv', CSV_MATRIX.encode())
        prev2 = ai.build_import_preview(self.tid, p2)
        pdec2, edec2 = self._decisions(prev2)
        b_skip = ai.confirm_import(self.tid, p2, pdec2, edec2, role='coach', overwrite_imported=False)
        self.assertEqual(b_skip.attendance_imported, 0)
        self.assertEqual(b_skip.skipped, 3)
        b_ow = ai.confirm_import(self.tid, p2, pdec2, edec2, role='coach', overwrite_imported=True)
        self.assertEqual(b_ow.overwritten, 3)

    def test_coachhub_attendance_never_overwritten(self):
        p = ai.parse_attendance_file('a.csv', CSV_MATRIX.encode())
        prev = ai.build_import_preview(self.tid, p)
        pdec, edec = self._decisions(prev)
        ai.confirm_import(self.tid, p, pdec, edec, role='coach')
        # promote one entry to a CoachHub coach edit
        e = AttendanceEntry.query.first()
        e.source = ai.SOURCE_COACH
        e.status = 'going'
        db.session.commit()
        p2 = ai.parse_attendance_file('a.csv', CSV_MATRIX.encode())
        prev2 = ai.build_import_preview(self.tid, p2)
        pdec2, edec2 = self._decisions(prev2)
        b = ai.confirm_import(self.tid, p2, pdec2, edec2, role='coach', overwrite_imported=True)
        # the coach entry stays coach + going; not counted as overwritten
        e2 = db.session.get(AttendanceEntry, e.id)
        self.assertEqual(e2.source, ai.SOURCE_COACH)
        self.assertGreaterEqual(b.skipped, 1)

    def test_rollback_removes_only_imported(self):
        p = ai.parse_attendance_file('a.csv', CSV_MATRIX.encode())
        prev = ai.build_import_preview(self.tid, p)
        pdec, edec = self._decisions(prev)
        batch = ai.confirm_import(self.tid, p, pdec, edec, role='coach')
        # mark one as coachhub -> must survive rollback
        e = AttendanceEntry.query.first()
        e.source = ai.SOURCE_COACH
        db.session.commit()
        removed = ai.rollback_import(self.tid, batch.id)
        self.assertEqual(removed, 2)                      # 3 imported - 1 promoted
        self.assertEqual(db.session.get(AttendanceImport, batch.id).status, 'rolled_back')
        self.assertEqual(AttendanceEntry.query.filter_by(source=ai.SOURCE_COACH).count(), 1)

    def test_ignore_player_and_event_decisions(self):
        p = ai.parse_attendance_file('a.csv', CSV_MATRIX.encode())
        prev = ai.build_import_preview(self.tid, p)
        pdec, edec = self._decisions(prev)
        # ignore Petr (new) entirely
        petr_idx = next(str(pl['idx']) for pl in prev['players'] if pl['name'] == 'Petr Svoboda')
        pdec[petr_idx] = 'ignore'
        batch = ai.confirm_import(self.tid, p, pdec, edec, role='coach')
        self.assertEqual(batch.players_created, 0)
        self.assertEqual(Player.query.filter_by(name='Petr Svoboda').count(), 0)

    def test_source_breakdown_and_recent_imports(self):
        p = ai.parse_attendance_file('a.csv', CSV_MATRIX.encode())
        prev = ai.build_import_preview(self.tid, p)
        pdec, edec = self._decisions(prev)
        ai.confirm_import(self.tid, p, pdec, edec, role='coach')
        bd = ai.source_breakdown(self.tid)
        self.assertEqual(bd[ai.SOURCE_IMPORT], 3)
        self.assertEqual(len(ai.recent_imports(self.tid)), 1)


if __name__ == '__main__':
    unittest.main()
