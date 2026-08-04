# -*- coding: utf-8 -*-
"""MySQL compatibility of the drill ordering.

Production (MySQL 8) returned HTTP 500 on /drills and /drills/select because
``Drill.category.asc().nullsfirst()`` compiles to PostgreSQL-style
``ORDER BY ... NULLS FIRST``, which MySQL rejects with error 1064. Because
/drills/select is the entry point of the training export flow, the export could
not be started at all.

The fix replaces it with a portable CASE expression (``_drill_ordering``). These
tests pin both halves: the SQL emitted for the MySQL dialect (compile-only, no
live server needed) and the resulting row order on the existing SQLite test DB.
"""
import ast
import os
import unittest

from sqlalchemy.dialects import mysql, sqlite

from coach.app import app
from coach.extensions import db
from coach.models import Drill, Team, TeamKey
from coach.blueprints.drills import _drill_ordering
from coach.services.keys import hash_team_key


def _order_by_clause(dialect):
    """Compiled ORDER BY tail of a drill listing for the given dialect."""
    stmt = Drill.query.order_by(*_drill_ordering()).statement
    sql = str(stmt.compile(dialect=dialect,
                           compile_kwargs={'literal_binds': True}))
    return sql.split('ORDER BY', 1)[1].strip()


class DrillOrderingCompilesForMySQLTest(unittest.TestCase):
    """Dialect-level compilation — no MySQL server required."""

    def setUp(self):
        self.ctx = app.app_context(); self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    def test_mysql_sql_has_no_nulls_first_or_last(self):
        sql = _order_by_clause(mysql.dialect()).upper()
        self.assertNotIn('NULLS FIRST', sql)
        self.assertNotIn('NULLS LAST', sql)
        self.assertNotIn('NULLS', sql)   # nothing NULLS-ordered at all

    def test_mysql_sql_uses_case_expression(self):
        sql = _order_by_clause(mysql.dialect()).upper()
        self.assertIn('CASE', sql)
        self.assertIn('WHEN', sql)
        self.assertIn('IS NULL', sql)
        self.assertIn('END', sql)

    def test_mysql_sql_orders_case_then_category_then_name(self):
        sql = _order_by_clause(mysql.dialect())
        # NULL categories sort to 0, everything else to 1 -> NULLs first.
        self.assertRegex(sql, r'CASE WHEN \(drill\.category IS NULL\) '
                              r'THEN 0 ELSE 1 END ASC')
        self.assertIn('drill.category ASC', sql)
        self.assertIn('drill.name ASC', sql)
        # Ordering keys appear in the intended precedence.
        self.assertLess(sql.index('END ASC'), sql.index('drill.category ASC'))
        self.assertLess(sql.index('drill.category ASC'), sql.index('drill.name ASC'))

    def test_sqlite_sql_is_the_same_portable_case(self):
        """SQLite keeps identical semantics — no dialect-conditional behaviour."""
        sql = _order_by_clause(sqlite.dialect()).upper()
        self.assertNotIn('NULLS', sql)
        self.assertIn('CASE', sql)


class NoNullsOrderingAnywhereTest(unittest.TestCase):
    """Repo-wide guard so the unportable construct cannot come back."""

    BANNED = {'nullsfirst', 'nullslast', 'nulls_first', 'nulls_last'}

    def _calls_banned_attr(self, path):
        """True if the module *calls* a NULLS-ordering method.

        Uses the AST so prose in comments and docstrings (this fix is explained
        in one) cannot trip the guard — only real attribute access counts.
        """
        with open(path, encoding='utf-8') as fh:
            try:
                tree = ast.parse(fh.read())
            except SyntaxError:
                return False
        return any(isinstance(node, ast.Attribute) and node.attr in self.BANNED
                   for node in ast.walk(tree))

    def test_runtime_code_has_no_nulls_ordering(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if d not in ('__pycache__', '.venv', 'tests')]
            for fn in filenames:
                if fn.endswith('.py') and self._calls_banned_attr(os.path.join(dirpath, fn)):
                    offenders.append(os.path.relpath(os.path.join(dirpath, fn), root))
        self.assertEqual(offenders, [], f'unportable NULLS ordering in: {offenders}')

    def test_guard_detects_a_planted_offender(self):
        """The guard must actually fail on a real call site."""
        tree = ast.parse('q.order_by(Drill.category.asc().nullsfirst())')
        self.assertTrue(any(isinstance(n, ast.Attribute) and n.attr in self.BANNED
                            for n in ast.walk(tree)))


class DrillOrderingRowOrderTest(unittest.TestCase):
    """Row order on the existing SQLite test database, plus the routes that
    production reported as HTTP 500."""

    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='HC Test'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('ck')))
        # Insert deliberately out of order so ORDER BY has to do the work.
        db.session.add_all([
            Drill(team_id=self.tid, name='Zakonceni', category='Utok'),
            Drill(team_id=self.tid, name='Bez kategorie B', category=None),
            Drill(team_id=self.tid, name='Blokovani', category='Obrana'),
            Drill(team_id=self.tid, name='Bez kategorie A', category=None),
            Drill(team_id=self.tid, name='Nahoz', category='Utok'),
        ])
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self, role='coach'):
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid; s['team_role'] = role; s['team_login'] = True

    def _ordered(self):
        return Drill.query.filter_by(team_id=self.tid).order_by(*_drill_ordering()).all()

    def test_null_categories_come_first(self):
        rows = self._ordered()
        self.assertIsNone(rows[0].category)
        self.assertIsNone(rows[1].category)
        self.assertIsNotNone(rows[2].category)

    def test_category_then_name_ascending(self):
        rows = self._ordered()
        self.assertEqual([d.name for d in rows], [
            'Bez kategorie A',   # category NULL, name A-Z
            'Bez kategorie B',
            'Blokovani',         # Obrana
            'Nahoz',             # Utok, name A-Z
            'Zakonceni',
        ])
        categories = [d.category for d in rows if d.category]
        self.assertEqual(categories, sorted(categories))

    # ---- the two routes that returned HTTP 500 on MySQL ----
    def test_drills_route_succeeds(self):
        self._login('coach')
        self.assertEqual(self.client.get('/drills').status_code, 200)

    def test_drills_select_route_succeeds(self):
        self._login('coach')
        self.assertEqual(self.client.get('/drills/select').status_code, 200)

    def test_drills_select_with_search_filter_succeeds(self):
        """The filtered branch builds the same ORDER BY."""
        self._login('coach')
        r = self.client.get('/drills/select?q=Nahoz')
        self.assertEqual(r.status_code, 200)
        self.assertIn('Nahoz', r.get_data(as_text=True))

    def test_drill_selection_page_supports_export_flow(self):
        """The export flow starts here: the page must render the POST form and
        selectable drill_ids that /drills/export_pdf consumes."""
        self._login('coach')
        h = self.client.get('/drills/select').get_data(as_text=True)
        self.assertIn('id="exportForm"', h)
        self.assertIn('/drills/export_pdf', h)
        self.assertIn('name="drill_ids"', h)
        self.assertIn('Bez kategorie A', h)

    # ---- the export endpoint itself ----
    def test_export_pdf_succeeds(self):
        """export_drills_pdf orders in Python (no ORDER BY), so it carries no
        NULLS-ordering risk — pinned here so the whole flow stays covered."""
        self._login('coach')
        ids = [str(d.id) for d in self._ordered()[:2]]
        r = self.client.post('/drills/export_pdf', data={'drill_ids': ids})
        self.assertEqual(r.status_code, 302)             # redirect to export result

    def test_export_pdf_query_emits_no_nulls_ordering(self):
        stmt = Drill.query.filter(Drill.id.in_([1, 2])).statement
        sql = str(stmt.compile(dialect=mysql.dialect(),
                               compile_kwargs={'literal_binds': True})).upper()
        self.assertNotIn('NULLS', sql)


if __name__ == '__main__':
    unittest.main()
