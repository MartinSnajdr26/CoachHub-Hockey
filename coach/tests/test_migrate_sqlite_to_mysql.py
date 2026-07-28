# -*- coding: utf-8 -*-
"""Focused tests for the SQLite -> MySQL migration utility.

These run entirely offline: no MySQL server, no Docker. They use temporary
SQLite databases (source + a second SQLite standing in for "target"), synthetic
SQLAlchemy metadata for graph/cycle cases, and monkeypatching to exercise the
CLI without a live target. The migration functions take engines and URL strings
separately, so a SQLite engine can be paired with a MySQL-flavoured URL string
to drive the dialect checks without connecting to MySQL.

An optional live-MySQL integration test is gated behind
``COACHHUB_MYSQL_TEST_URL`` and skipped by default.
"""
import os
import tempfile
import unittest
from datetime import date, datetime, time

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    insert,
    select,
    text,
)
from sqlalchemy.types import Boolean, Date, DateTime, JSON, LargeBinary, Numeric, Time

import coach.scripts.migrate_sqlite_to_mysql as M

HEAD = M.expected_head()


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #

def _stamp_alembic(engine, rev=HEAD):
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS alembic_version "
            "(version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("DELETE FROM alembic_version"))
        conn.execute(text("INSERT INTO alembic_version VALUES (:v)"), {"v": rev})


def _new_sqlite(tmpdir, name):
    path = os.path.join(tmpdir, name)
    return path, create_engine(f"sqlite:///{path}", future=True)


def _create_schema(engine, metadata):
    # Only the application tables (metadata has exactly those).
    metadata.create_all(engine)


DT = datetime(2026, 7, 20, 10, 30, 0)


def _seed_source(engine, md):
    """Insert a small, type-diverse, Unicode-heavy dataset into the source."""
    T = {t.name: t for t in md.tables.values()}
    with engine.begin() as c:
        c.execute(insert(T["team"]), [
            {"id": 1, "name": "Sparta Praha 🏒", "created_at": DT,
             "last_active_at": None},                      # emoji + NULL
            {"id": 2, "name": "Görlitz Éčko", "created_at": DT,
             "last_active_at": None},                      # umlaut + accent
        ])
        c.execute(insert(T["player"]), [
            {"id": 1, "team_id": 1, "name": "Jágr Ová", "position": "F"},
            {"id": 2, "team_id": 1, "name": "日本語プレイヤー", "position": "G"},
            {"id": 3, "team_id": 2, "name": "", "position": "D"},   # empty string
        ])
        c.execute(insert(T["team_key"]), [
            {"id": 1, "team_id": 1, "role": "coach", "key_hash": "h" * 60,
             "active": True, "created_at": DT},
            {"id": 2, "team_id": 1, "role": "player", "key_hash": "k",
             "active": False, "created_at": DT},            # boolean False
        ])
        c.execute(insert(T["training_event"]), [
            {"id": 1, "team_id": 1, "day": date(2026, 7, 20), "time": "10:30",
             "title": "Trénink", "source": "coachhub_manual", "created_at": DT},
        ])
        c.execute(insert(T["attendance_entry"]), [
            {"id": 1, "team_id": 1, "player_id": 1, "event_key": "k1",
             "event_title": "", "event_day": date(2026, 7, 20), "status": "going",
             "source": "coachhub_coach", "updated_at": DT},   # empty event_title
        ])
        c.execute(insert(T["league_integration"]), [
            {"id": 1, "team_id": 1, "enabled": False,
             "data_json": '{"standings": [1, 2, 3]}', "created_at": DT},
        ])
        c.execute(insert(T["payment_period"]), [
            {"id": 1, "team_id": 1, "year": 2026, "month": 7, "amount": 500,
             "created_at": DT},
        ])
        c.execute(insert(T["payment_status"]), [
            {"id": 1, "team_id": 1, "period_id": 1, "player_id": 1,
             "status": "paid", "updated_at": DT},
        ])
        c.execute(insert(T["audit_event"]), [
            {"id": 1, "event": "login", "team_id": 1, "meta": '{"x": 1}',
             "created_at": DT},
        ])


class _E2EBase(unittest.TestCase):
    """Builds a populated source + empty target (both SQLite) sharing metadata."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.md = M.load_metadata()
        self.src_path, self.src = _new_sqlite(self.tmp, "source.db")
        self.tgt_path, self.tgt = _new_sqlite(self.tmp, "target.db")
        _create_schema(self.src, self.md)
        _create_schema(self.tgt, self.md)
        _stamp_alembic(self.src)
        _stamp_alembic(self.tgt)
        _seed_source(self.src, self.md)
        # URL strings drive dialect checks; engines do the real work.
        self.src_url = f"sqlite:///{self.src_path}"
        self.tgt_url = "mysql+pymysql://user:pw@mysql.example/db?charset=utf8mb4"

    def _copy_all(self):
        for tbl in M.dependency_order(self.md):
            M.copy_table(self.src, self.tgt, tbl, batch_size=2)


# --------------------------------------------------------------------------- #
# Env / dialect / sanitization (Phase 3)
# --------------------------------------------------------------------------- #

class EnvAndUrlTests(unittest.TestCase):
    def test_missing_source_url(self):
        old = dict(os.environ)
        try:
            os.environ.pop("SQLITE_SOURCE_URL", None)
            os.environ["MYSQL_TARGET_URL"] = "mysql+pymysql://u:p@h/db"
            self.assertEqual(M.main(["--dry-run"]), M.EXIT_USAGE)
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_missing_target_url(self):
        old = dict(os.environ)
        try:
            os.environ["SQLITE_SOURCE_URL"] = "sqlite:///x.db"
            os.environ.pop("MYSQL_TARGET_URL", None)
            self.assertEqual(M.main(["--dry-run"]), M.EXIT_USAGE)
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_sanitize_hides_password(self):
        s = M.sanitize_url(
            "mysql+pymysql://martinsnajdr:SUPERSECRET@host/db?charset=utf8mb4")
        self.assertNotIn("SUPERSECRET", s)
        self.assertIn("password_present=yes", s)
        self.assertIn("dialect=mysql", s)
        self.assertIn("host=host", s)

    def test_sanitize_no_password(self):
        s = M.sanitize_url("sqlite:////home/x/app.db")
        self.assertIn("password_present=no", s)
        self.assertIn("dialect=sqlite", s)


class DialectAndFileChecks(_E2EBase):
    def test_invalid_source_dialect_fails(self):
        checks, safe = M.preflight(
            self.src, self.tgt,
            "mysql+pymysql://u:p@h/db",  # source claims mysql -> invalid
            self.tgt_url, self.md, require_empty_target=True)
        by = {n: ok for n, ok, _ in checks}
        self.assertFalse(by["source dialect is sqlite"])

    def test_invalid_target_dialect_fails(self):
        checks, safe = M.preflight(
            self.src, self.tgt, self.src_url,
            "sqlite:///also_sqlite.db",  # target claims sqlite -> invalid
            self.md, require_empty_target=True)
        by = {n: ok for n, ok, _ in checks}
        self.assertFalse(by["target dialect is mysql"])

    def test_missing_source_file_fails(self):
        checks, safe = M.preflight(
            self.src, self.tgt,
            "sqlite:////nonexistent/definitely/missing.db",
            self.tgt_url, self.md, require_empty_target=True)
        by = {n: ok for n, ok, _ in checks}
        self.assertFalse(by["source sqlite file exists"])

    def test_alembic_revision_mismatch_detected(self):
        _stamp_alembic(self.tgt, rev="deadbeef0000")
        checks, safe = M.preflight(
            self.src, self.tgt, self.src_url, self.tgt_url, self.md,
            require_empty_target=True)
        by = {n: ok for n, ok, _ in checks}
        self.assertFalse(by["target alembic revision == head"])
        self.assertFalse(safe)

    def test_clean_preflight_passes(self):
        checks, safe = M.preflight(
            self.src, self.tgt, self.src_url, self.tgt_url, self.md,
            require_empty_target=True)
        self.assertTrue(safe, msg=str([c for c in checks if not c[1]]))


# --------------------------------------------------------------------------- #
# Exclusions (audit_log / alembic_version)
# --------------------------------------------------------------------------- #

class ExclusionTests(unittest.TestCase):
    def test_excluded_set(self):
        self.assertIn("audit_log", M.EXCLUDED_TABLES)
        self.assertIn("alembic_version", M.EXCLUDED_TABLES)

    def test_audit_log_not_in_application_tables(self):
        md = M.load_metadata()
        names = {t.name for t in M.application_tables(md)}
        self.assertNotIn("audit_log", names)
        self.assertNotIn("alembic_version", names)

    def test_alembic_version_never_copied(self):
        # alembic_version is not in the dependency order that copy iterates.
        md = M.load_metadata()
        names = [t.name for t in M.dependency_order(md)]
        self.assertNotIn("alembic_version", names)
        self.assertNotIn("audit_log", names)


# --------------------------------------------------------------------------- #
# Dependency ordering & cycle detection (Phase 4)
# --------------------------------------------------------------------------- #

class DependencyOrderTests(unittest.TestCase):
    def test_parents_before_children(self):
        md = M.load_metadata()
        order = [t.name for t in M.dependency_order(md)]
        self.assertLess(order.index("team"), order.index("player"))
        self.assertLess(order.index("player"), order.index("roster"))
        self.assertLess(order.index("player"), order.index("attendance_entry"))
        self.assertLess(order.index("payment_period"), order.index("payment_status"))
        self.assertLess(order.index("player"), order.index("payment_status"))

    def test_deterministic(self):
        md = M.load_metadata()
        a = [t.name for t in M.dependency_order(md)]
        b = [t.name for t in M.dependency_order(md)]
        self.assertEqual(a, b)

    def test_cycle_detection(self):
        m = MetaData()
        Table("a", m, Column("id", Integer, primary_key=True),
              Column("b_id", Integer, ForeignKey("b.id")))
        Table("b", m, Column("id", Integer, primary_key=True),
              Column("a_id", Integer, ForeignKey("a.id")))
        with self.assertRaises(ValueError):
            M.dependency_order(m)

    def test_self_reference_is_not_a_cycle(self):
        m = MetaData()
        Table("node", m, Column("id", Integer, primary_key=True),
              Column("parent_id", Integer, ForeignKey("node.id")))
        order = [t.name for t in M.dependency_order(m)]
        self.assertEqual(order, ["node"])


# --------------------------------------------------------------------------- #
# Type normalization (Phase 6)
# --------------------------------------------------------------------------- #

class NormalizationTests(unittest.TestCase):
    def test_boolean(self):
        self.assertIs(M.normalize_value(1, Boolean()), True)
        self.assertIs(M.normalize_value(0, Boolean()), False)
        self.assertIs(M.normalize_value("true", Boolean()), True)

    def test_date_datetime_time_from_string(self):
        self.assertEqual(M.normalize_value("2026-07-20", Date()), date(2026, 7, 20))
        self.assertEqual(M.normalize_value("2026-07-20 10:30:00", DateTime()),
                         datetime(2026, 7, 20, 10, 30))
        self.assertEqual(M.normalize_value("2026-07-20T10:30:00", DateTime()),
                         datetime(2026, 7, 20, 10, 30))
        self.assertEqual(M.normalize_value("10:30:00", Time()), time(10, 30))

    def test_json_native_type(self):
        self.assertEqual(M.normalize_value('{"a": 1}', JSON()), {"a": 1})
        self.assertEqual(M.normalize_value([1, 2], JSON()), [1, 2])

    def test_binary_memoryview(self):
        out = M.normalize_value(memoryview(b"\x00\x01"), LargeBinary())
        self.assertEqual(out, b"\x00\x01")
        self.assertIsInstance(out, bytes)

    def test_numeric_precision(self):
        from decimal import Decimal
        self.assertEqual(M.normalize_value("10.25", Numeric()), Decimal("10.25"))

    def test_null_and_empty_string_preserved(self):
        self.assertIsNone(M.normalize_value(None, DateTime()))
        self.assertEqual(M.normalize_value("", String(10)), "")


# --------------------------------------------------------------------------- #
# String-length overflow (Phase 6)
# --------------------------------------------------------------------------- #

class LengthOverflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.md = M.load_metadata()
        self.path, self.eng = _new_sqlite(self.tmp, "len.db")
        _create_schema(self.eng, self.md)
        self.T = {t.name: t for t in self.md.tables.values()}

    def test_overflow_detected(self):
        # player.name is String(100); insert 150 chars -> overflow vs VARCHAR(100).
        with self.eng.begin() as c:
            c.execute(insert(self.T["team"]), {"id": 1, "name": "t"})
            c.execute(insert(self.T["player"]),
                      {"id": 1, "team_id": 1, "name": "x" * 150, "position": "F"})
        findings = M.scan_length_overflows(self.eng, self.T["player"], {})
        name = [f for f in findings if f["column"] == "name"][0]
        self.assertTrue(name["overflow"])
        self.assertEqual(name["capacity"], 100)
        self.assertEqual(name["max_source"], 150)

    def test_no_overflow_when_within_capacity(self):
        with self.eng.begin() as c:
            c.execute(insert(self.T["team"]), {"id": 1, "name": "t"})
            c.execute(insert(self.T["player"]),
                      {"id": 1, "team_id": 1, "name": "ok", "position": "F"})
        findings = M.scan_length_overflows(self.eng, self.T["player"], {})
        self.assertTrue(all(not f["overflow"] for f in findings))

    def test_text_byte_capacity_mapping(self):
        self.assertEqual(M.target_capacity(String(50)), ("chars", 50))
        # a generic Text maps to MySQL TEXT byte capacity
        from sqlalchemy.types import Text
        self.assertEqual(M.target_capacity(Text()), ("bytes", 65_535))


# --------------------------------------------------------------------------- #
# AUTO_INCREMENT (Phase 7)
# --------------------------------------------------------------------------- #

class AutoIncrementTests(unittest.TestCase):
    def test_next_value(self):
        self.assertEqual(M.next_autoincrement_value(None), 1)
        self.assertEqual(M.next_autoincrement_value(55), 56)

    def test_all_model_pks_are_autoincrement_candidates(self):
        md = M.load_metadata()
        names = {t.name for t, _pk in M.autoincrement_tables(md)}
        self.assertEqual(names, {t.name for t in M.application_tables(md)})

    def test_composite_and_string_pk_skipped(self):
        m = MetaData()
        Table("cpk", m, Column("x", Integer, primary_key=True),
              Column("y", Integer, primary_key=True))
        Table("spk", m, Column("code", String(10), primary_key=True))
        got = {t.name for t, _pk in M.autoincrement_tables(m)}
        self.assertNotIn("cpk", got)
        self.assertNotIn("spk", got)

    def test_pk_columns_composite(self):
        m = MetaData()
        t = Table("cpk", m, Column("x", Integer, primary_key=True),
                  Column("y", Integer, primary_key=True))
        self.assertEqual(M.pk_columns(t), ["x", "y"])


# --------------------------------------------------------------------------- #
# End-to-end copy + validation (Phases 5 & 8)
# --------------------------------------------------------------------------- #

class CopyAndValidateTests(_E2EBase):
    def test_copy_preserves_everything(self):
        self._copy_all()
        results, ok = M.validate(self.src, self.tgt, self.md)
        self.assertTrue(ok, msg=str([r for r in results if r["status"] != "OK"]))
        # Unicode / bool / empty-string round trip through the target verbatim.
        T = {t.name: t for t in self.md.tables.values()}
        with self.tgt.connect() as c:
            names = [r[0] for r in c.execute(
                select(T["player"].c.name).order_by(T["player"].c.id))]
            self.assertEqual(names, ["Jágr Ová", "日本語プレイヤー", ""])
            active = [r[0] for r in c.execute(
                select(T["team_key"].c.active).order_by(T["team_key"].c.id))]
            self.assertEqual([bool(a) for a in active], [True, False])

    def test_validation_row_count_mismatch(self):
        self._copy_all()
        T = {t.name: t for t in self.md.tables.values()}
        with self.tgt.begin() as c:
            c.execute(T["audit_event"].delete())   # drop target rows
        results, ok = M.validate(self.src, self.tgt, self.md)
        self.assertFalse(ok)
        row = [r for r in results if r["table"] == "audit_event"][0]
        self.assertNotEqual(row["source"], row["target"])
        self.assertEqual(row["status"], "FAIL")

    def test_validation_pk_mismatch(self):
        self._copy_all()
        T = {t.name: t for t in self.md.tables.values()}
        # Same count, different PK value -> PK digest differs.
        with self.tgt.begin() as c:
            c.execute(T["audit_event"].update()
                      .where(T["audit_event"].c.id == 1).values(id=999))
        results, ok = M.validate(self.src, self.tgt, self.md)
        row = [r for r in results if r["table"] == "audit_event"][0]
        self.assertFalse(row["pk_match"])
        self.assertFalse(ok)

    def test_fk_orphan_detection(self):
        self._copy_all()
        T = {t.name: t for t in self.md.tables.values()}
        # Point a child FK at a non-existent parent (PRAGMA FKs are off in SQLite).
        with self.tgt.begin() as c:
            c.execute(T["player"].update()
                      .where(T["player"].c.id == 1).values(team_id=8888))
        self.assertGreater(M.fk_orphan_count(self.tgt, T["player"]), 0)
        results, ok = M.validate(self.src, self.tgt, self.md)
        self.assertFalse(ok)


# --------------------------------------------------------------------------- #
# Non-empty refusal + dry-run makes no writes (Phases 9 & 10)
# --------------------------------------------------------------------------- #

class RefusalAndDryRunTests(_E2EBase):
    def test_execute_refuses_non_empty_target(self):
        # Pre-populate the target so it is NOT empty.
        self._copy_all()
        before = M.table_row_count(self.tgt, {t.name: t for t in
                                              self.md.tables.values()}["team"])
        checks, safe = M.preflight(self.src, self.tgt, self.src_url, self.tgt_url,
                                   self.md, require_empty_target=True)
        by = {n: ok for n, ok, _ in checks}
        self.assertFalse(by["target application tables are empty"])
        self.assertFalse(safe)
        # nothing changed
        after = M.table_row_count(self.tgt, {t.name: t for t in
                                             self.md.tables.values()}["team"])
        self.assertEqual(before, after)

    def test_dry_run_writes_nothing(self):
        real_build = M.build_engine
        engine_map = {self.src_url: self.src, self.tgt_url: self.tgt}
        old = dict(os.environ)
        try:
            M.build_engine = lambda url: engine_map[url]   # avoid real MySQL
            os.environ["SQLITE_SOURCE_URL"] = self.src_url
            os.environ["MYSQL_TARGET_URL"] = self.tgt_url
            rc = M.main(["--dry-run"])
        finally:
            M.build_engine = real_build
            os.environ.clear()
            os.environ.update(old)
        # target started empty and must stay empty
        for tbl in M.dependency_order(self.md):
            self.assertEqual(M.table_row_count(self.tgt, tbl), 0,
                             msg=f"dry-run wrote to {tbl.name}")
        self.assertEqual(rc, M.EXIT_OK)


# --------------------------------------------------------------------------- #
# Optional live MySQL integration (skipped unless explicitly enabled)
# --------------------------------------------------------------------------- #

@unittest.skipUnless(os.getenv("COACHHUB_MYSQL_TEST_URL"),
                     "set COACHHUB_MYSQL_TEST_URL to run the live MySQL test")
class LiveMysqlIntegrationTest(unittest.TestCase):  # pragma: no cover
    def test_smoke(self):
        url = os.environ["COACHHUB_MYSQL_TEST_URL"]
        eng = M.build_engine(url)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))


if __name__ == "__main__":
    unittest.main()
