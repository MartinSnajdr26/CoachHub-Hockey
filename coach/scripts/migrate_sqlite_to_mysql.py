#!/usr/bin/env python3
"""One-time SQLite -> MySQL data migration for CoachHub Hockey.

Copies application-table ROWS from the production SQLite database into an
already-Alembic-provisioned MySQL schema. It is schema-agnostic: the table set,
columns, types, foreign keys and safe insert order are all read from the live
SQLAlchemy metadata (``coach.models``), so the utility never drifts from the
models and needs no per-table configuration.

Exactly one mode is required:

  --dry-run        Inspect only. No writes anywhere. Reports sanitized
                   connection details, integrity, Alembic revisions, table
                   inventory, exclusions, target emptiness, dependency order,
                   row counts, type/length findings and AUTO_INCREMENT tables.
                   Exits non-zero if execution would be unsafe.

  --execute        Copy data (refuses if ANY target application table already
                   has rows). Copies in FK-dependency order, one transaction
                   per table, reseeds AUTO_INCREMENT, then runs validation.

  --validate-only  Compare source vs target (row counts, PK sets/digests,
                   per-column NULL counts, FK orphans, column inventory,
                   content digest). No writes.

Environment (never printed in full):

  SQLITE_SOURCE_URL   e.g. sqlite:////home/martinsnajdr/coach/instance/app.db
  MYSQL_TARGET_URL    e.g. mysql+pymysql://user:pw@host/db?charset=utf8mb4

Hard rules baked in:
  * NEVER migrates ``alembic_version`` or the obsolete ``audit_log`` table.
  * NEVER runs ``create_all``/DDL, never truncates/overwrites/merges target data.
  * NEVER prints credential-bearing URLs or row contents — only table names,
    counts, and status.

This file is import-safe (no side effects at import); the CLI runs only under
``__main__``.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.types import (
    Boolean,
    Date,
    DateTime,
    LargeBinary,
    Numeric,
    String,
    Text,
    Time,
)

try:  # SQLAlchemy has a generic JSON type; guard in case of very old versions.
    from sqlalchemy.types import JSON
except Exception:  # pragma: no cover
    JSON = None  # type: ignore

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

#: Tables that must NEVER be touched by this data copy.
#: - alembic_version: schema-version bookkeeping (managed by Alembic, not data).
#: - audit_log: obsolete orphan table, 0 rows, not in SQLAlchemy metadata.
EXCLUDED_TABLES = frozenset({"alembic_version", "audit_log"})

DEFAULT_BATCH_SIZE = 500

# MySQL TEXT-family byte capacities (utf8mb4 stores up to 4 bytes/char).
_MYSQL_TEXT_BYTES = {
    "TINYTEXT": 255,
    "TEXT": 65_535,
    "MEDIUMTEXT": 16_777_215,
    "LONGTEXT": 4_294_967_295,
}

# Exit codes
EXIT_OK = 0
EXIT_UNSAFE = 1
EXIT_USAGE = 2


# --------------------------------------------------------------------------- #
# Small utilities
# --------------------------------------------------------------------------- #

def log(msg: str = "") -> None:
    """Print a progress line (never row contents or credentials)."""
    print(msg, flush=True)


def sanitize_url(url: str) -> str:
    """Return a credential-free one-line description of a DB URL.

    Reports only dialect, username, host, database and whether a password is
    present — never the password itself or the full URL.
    """
    try:
        u = make_url(url)
    except Exception:
        return "dialect=<unparseable> user=? host=? db=? password_present=?"
    return (
        f"dialect={u.get_backend_name()} "
        f"user={u.username or '-'} "
        f"host={u.host or '-'} "
        f"db={u.database or '-'} "
        f"password_present={'yes' if u.password else 'no'}"
    )


def repo_root() -> str:
    """Repository root (the parent of the ``coach`` package)."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def migrations_dir() -> str:
    return os.path.join(repo_root(), "migrations")


def expected_head() -> str:
    """Derive the expected Alembic head from the local migrations directory.

    Single source of truth: reads ``migrations/`` rather than hard-coding a
    revision in several places. Raises if there is not exactly one head.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config()
    cfg.set_main_option("script_location", migrations_dir())
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    if len(heads) != 1:
        raise RuntimeError(
            f"Expected exactly one Alembic head, found {len(heads)}: {heads}"
        )
    return heads[0]


def load_metadata():
    """Return the app's SQLAlchemy MetaData (models registered, no app/DB bind).

    Importing ``coach.models`` registers every model in ``db.metadata`` without
    creating the Flask app or opening any database connection.
    """
    import coach.models as models  # noqa: WPS433 (local import keeps import-safety)

    return models.db.metadata


def application_tables(metadata):
    """Metadata Table objects for the application, excluding EXCLUDED_TABLES.

    ``audit_log``/``alembic_version`` are not in the model metadata anyway; the
    filter is defensive.
    """
    return [t for t in metadata.tables.values() if t.name not in EXCLUDED_TABLES]


# --------------------------------------------------------------------------- #
# Dependency ordering (Phase 4)
# --------------------------------------------------------------------------- #

def dependency_order(metadata):
    """Return application tables in FK-safe insert order (parents first).

    Deterministic (ties broken by table name) and cycle-detecting. Self-
    referential foreign keys do not create inter-table cycles and are ignored
    for ordering. Raises ``ValueError`` on an unbreakable cycle.
    """
    tables = {t.name: t for t in application_tables(metadata)}

    # Build dependency edges: table -> set(parent tables it references).
    deps: dict[str, set[str]] = {name: set() for name in tables}
    for name, tbl in tables.items():
        for fk in tbl.foreign_keys:
            parent = fk.column.table.name
            if parent in EXCLUDED_TABLES or parent == name:
                continue
            if parent in tables:
                deps[name].add(parent)

    # Kahn's algorithm, always taking the smallest-named ready node (stable).
    ordered: list = []
    resolved: set[str] = set()
    remaining = set(tables)
    while remaining:
        ready = sorted(n for n in remaining if deps[n] <= resolved)
        if not ready:
            cycle = sorted(remaining)
            raise ValueError(
                "Foreign-key cycle detected among tables; cannot derive a safe "
                f"insert order without disabling FK checks: {cycle}"
            )
        for name in ready:
            ordered.append(tables[name])
            resolved.add(name)
            remaining.discard(name)
    return ordered


# --------------------------------------------------------------------------- #
# Type normalization (Phase 6)
# --------------------------------------------------------------------------- #

def _parse_datetime(value: str):
    s = value.strip()
    if not s:
        return value
    s = s.replace("T", " ")
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unparseable datetime string (len={len(value)})")


def _parse_date(value: str):
    s = value.strip()
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return _parse_datetime(s).date()


def _parse_time(value: str):
    s = value.strip()
    for fmt in ("%H:%M:%S.%f", "%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Unparseable time string (len={len(value)})")


def normalize_value(value, coltype):
    """Coerce a source value to the Python type MySQL expects for ``coltype``.

    NULL and empty-string are preserved distinctly; no silent truncation or
    lossy coercion. Raises on values that cannot be represented safely.
    """
    if value is None:
        return None

    # Booleans: SQLite often yields 0/1 ints.
    if isinstance(coltype, Boolean):
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return bool(value)
        if isinstance(value, str):
            low = value.strip().lower()
            if low in ("1", "true", "t", "yes", "y"):
                return True
            if low in ("0", "false", "f", "no", "n", ""):
                return False
        raise ValueError("Non-coercible boolean value")

    # Native JSON columns (none today, but keep type-driven & correct).
    if JSON is not None and isinstance(coltype, JSON):
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, (bytes, bytearray, memoryview)):
            value = bytes(value).decode("utf-8")
        if isinstance(value, str):
            import json

            return json.loads(value)
        return value

    # Datetime / date / time from strings (SQLite stores these as text).
    if isinstance(coltype, DateTime):
        return value if isinstance(value, datetime) else _parse_datetime(str(value))
    if isinstance(coltype, Date):
        if isinstance(value, datetime):
            return value.date()
        return value if isinstance(value, date) else _parse_date(str(value))
    if isinstance(coltype, Time):
        return value if isinstance(value, time) else _parse_time(str(value))

    # Binary columns: normalize buffer types to bytes.
    if isinstance(coltype, LargeBinary):
        if isinstance(value, memoryview):
            return value.tobytes()
        if isinstance(value, bytearray):
            return bytes(value)
        return value

    # Numeric/Decimal: keep exact precision.
    if isinstance(coltype, Numeric):
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise ValueError("Non-coercible numeric value")

    # String/Text/Integer and everything else: pass through unchanged
    # (empty string stays "", never becomes NULL).
    return value


# --------------------------------------------------------------------------- #
# String-length / capacity checks (Phase 6)
# --------------------------------------------------------------------------- #

def _value_sizes(value):
    """Return (character_count, utf8_byte_count) for a text value, else None."""
    if isinstance(value, str):
        return len(value), len(value.encode("utf-8"))
    if isinstance(value, (bytes, bytearray, memoryview)):
        b = bytes(value)
        return len(b), len(b)
    return None


def target_capacity(coltype, inspected_type=None):
    """Bounded capacity of a target column, or None if unbounded/non-text.

    Returns ``("chars", n)`` for VARCHAR(n) or ``("bytes", n)`` for a MySQL
    TEXT-family column. ``inspected_type`` (from a live inspector) takes
    precedence for TEXT-family sizing when available.
    """
    # VARCHAR-style: character-limited.
    length = getattr(coltype, "length", None)
    if isinstance(coltype, String) and not isinstance(coltype, Text) and length:
        return ("chars", int(length))

    # TEXT-family: byte-limited. Prefer the inspected concrete MySQL type.
    probe = inspected_type if inspected_type is not None else coltype
    cls_name = type(probe).__name__.upper()
    if cls_name in _MYSQL_TEXT_BYTES:
        return ("bytes", _MYSQL_TEXT_BYTES[cls_name])
    if isinstance(coltype, Text):
        # Generic Text with no concrete MySQL mapping available -> assume TEXT.
        return ("bytes", _MYSQL_TEXT_BYTES["TEXT"])
    if isinstance(coltype, String) and length:
        return ("chars", int(length))
    return None


def scan_length_overflows(source_engine: Engine, table, target_types=None):
    """Scan a source table for values that would overflow bounded target columns.

    ``target_types`` maps column name -> inspected concrete target type (from a
    live MySQL inspector). Returns a list of finding dicts (never values).
    """
    target_types = target_types or {}
    findings = []
    # Columns worth scanning: those with a bounded capacity.
    caps = {}
    for col in table.columns:
        cap = target_capacity(col.type, target_types.get(col.name))
        if cap is not None:
            caps[col.name] = cap
    if not caps:
        return findings

    max_seen = {name: 0 for name in caps}
    cols = [table.c[name] for name in caps]
    with source_engine.connect() as conn:
        result = conn.execution_options(stream_results=True).execute(select(*cols))
        for row in result:
            m = row._mapping
            for name, (unit, _cap) in caps.items():
                sizes = _value_sizes(m[name])
                if sizes is None:
                    continue
                measured = sizes[0] if unit == "chars" else sizes[1]
                if measured > max_seen[name]:
                    max_seen[name] = measured

    for name, (unit, cap) in caps.items():
        over = max_seen[name] > cap
        findings.append(
            {
                "table": table.name,
                "column": name,
                "unit": unit,
                "max_source": max_seen[name],
                "capacity": cap,
                "overflow": over,
            }
        )
    return findings


# --------------------------------------------------------------------------- #
# AUTO_INCREMENT (Phase 7)
# --------------------------------------------------------------------------- #

def autoincrement_tables(metadata):
    """Tables whose single integer PK is an AUTO_INCREMENT candidate.

    Skips composite PKs and non-integer (e.g. string) PKs. Returns a list of
    ``(table, pk_column_name)``.
    """
    from sqlalchemy.types import Integer

    result = []
    for tbl in application_tables(metadata):
        pk_cols = list(tbl.primary_key.columns)
        if len(pk_cols) != 1:
            continue  # composite PK -> not a simple AUTO_INCREMENT
        col = pk_cols[0]
        if not isinstance(col.type, Integer):
            continue  # non-integer PK
        if col.autoincrement is False:
            continue
        result.append((tbl, col.name))
    return result


def next_autoincrement_value(max_pk):
    """Next AUTO_INCREMENT value given the current max PK (None -> 1)."""
    if max_pk is None:
        return 1
    return int(max_pk) + 1


def reseed_autoincrements(target_engine: Engine, metadata):
    """Set each AUTO_INCREMENT to max(pk)+1 on the target. Identifiers quoted."""
    preparer = target_engine.dialect.identifier_preparer
    reseeded = []
    for tbl, pk_name in autoincrement_tables(metadata):
        with target_engine.connect() as conn:
            max_pk = conn.execute(select(func.max(tbl.c[pk_name]))).scalar()
            nxt = next_autoincrement_value(max_pk)
            qtable = preparer.quote(tbl.name)
            # AUTO_INCREMENT cannot be a bound parameter; nxt is a validated int.
            conn.execute(text(f"ALTER TABLE {qtable} AUTO_INCREMENT = {int(nxt)}"))
            conn.commit()
        reseeded.append((tbl.name, nxt))
    return reseeded


# --------------------------------------------------------------------------- #
# Connections & preflight (Phase 3)
# --------------------------------------------------------------------------- #

def build_engine(url: str) -> Engine:
    """Create an Engine. SQLite-only connect args are never applied to MySQL."""
    return create_engine(url, future=True)


def sqlite_file_path(url: str):
    try:
        return make_url(url).database
    except Exception:
        return None


def sqlite_integrity_ok(engine: Engine) -> bool:
    with engine.connect() as conn:
        row = conn.execute(text("PRAGMA integrity_check")).fetchone()
    return bool(row) and str(row[0]).lower() == "ok"


def read_alembic_version(engine: Engine):
    """Return the target's stored Alembic revision, or None if absent."""
    insp = inspect(engine)
    if "alembic_version" not in insp.get_table_names():
        return None
    with engine.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
    return row[0] if row else None


def table_row_count(engine: Engine, table) -> int:
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(table)).scalar() or 0)


def preflight(source_engine, target_engine, source_url, target_url, metadata,
              require_empty_target):
    """Run all safety checks. Returns (checks, safe) where checks is a list of
    (name, ok, detail) and ``safe`` is the AND of all hard checks."""
    checks = []

    def add(name, ok, detail=""):
        checks.append((name, bool(ok), detail))
        return ok

    head = expected_head()

    # Dialects & URLs
    su = make_url(source_url)
    tu = make_url(target_url)
    add("source dialect is sqlite", su.get_backend_name() == "sqlite",
        su.get_backend_name())
    add("target dialect is mysql", tu.get_backend_name() == "mysql",
        tu.get_backend_name())
    add("source and target differ", str(su) != str(tu))

    # Source file exists
    path = sqlite_file_path(source_url)
    add("source sqlite file exists", bool(path) and os.path.exists(path),
        path or "-")

    # Connectivity
    src_ok = tgt_ok = False
    try:
        with source_engine.connect():
            src_ok = True
    except Exception as exc:  # noqa: BLE001
        add("source connection", False, type(exc).__name__)
    if src_ok:
        add("source connection", True)
        # Integrity
        try:
            add("source integrity_check == ok", sqlite_integrity_ok(source_engine))
        except Exception as exc:  # noqa: BLE001
            add("source integrity_check == ok", False, type(exc).__name__)
    try:
        with target_engine.connect():
            tgt_ok = True
    except Exception as exc:  # noqa: BLE001
        add("target connection", False, type(exc).__name__)
    if tgt_ok:
        add("target connection", True)

    # Alembic revisions
    if src_ok:
        try:
            sv = read_alembic_version(source_engine)
            add("source alembic revision == head", sv == head, f"{sv} vs {head}")
        except Exception as exc:  # noqa: BLE001
            add("source alembic revision == head", False, type(exc).__name__)
    if tgt_ok:
        try:
            tv = read_alembic_version(target_engine)
            add("target alembic revision == head", tv == head, f"{tv} vs {head}")
        except Exception as exc:  # noqa: BLE001
            add("target alembic revision == head", False, type(exc).__name__)

    # Table presence in both DBs
    model_tables = sorted(t.name for t in application_tables(metadata))
    if src_ok:
        src_tables = set(inspect(source_engine).get_table_names())
        missing = [t for t in model_tables if t not in src_tables]
        add("all model tables exist in source", not missing,
            f"missing={missing}" if missing else "")
    if tgt_ok:
        tgt_tables = set(inspect(target_engine).get_table_names())
        missing = [t for t in model_tables if t not in tgt_tables]
        add("all model tables exist in target", not missing,
            f"missing={missing}" if missing else "")

    # Target emptiness (hard only when required, i.e. --execute)
    if tgt_ok:
        nonempty = []
        for tbl in application_tables(metadata):
            try:
                if table_row_count(target_engine, tbl) > 0:
                    nonempty.append(tbl.name)
            except Exception:  # noqa: BLE001
                pass
        detail = f"non-empty={nonempty}" if nonempty else "all empty"
        if require_empty_target:
            add("target application tables are empty", not nonempty, detail)
        else:
            checks.append(("target application tables empty (info)",
                           not nonempty, detail))

    # Informational: exclusions are honored
    checks.append(("alembic_version excluded (info)", True, "ignored as bookkeeping"))
    checks.append(("audit_log excluded (info)", "audit_log" not in model_tables,
                   "not in metadata; never migrated"))

    hard = [ok for (name, ok, _d) in checks if "(info)" not in name]
    return checks, all(hard)


# --------------------------------------------------------------------------- #
# Data copy (Phase 5)
# --------------------------------------------------------------------------- #

def _read_batches(source_engine: Engine, table, batch_size):
    coltypes = {c.name: c.type for c in table.columns}
    with source_engine.connect() as conn:
        result = conn.execution_options(stream_results=True).execute(table.select())
        while True:
            rows = result.fetchmany(batch_size)
            if not rows:
                break
            yield [
                {name: normalize_value(r._mapping[name], coltypes[name])
                 for name in coltypes}
                for r in rows
            ]


def copy_table(source_engine, target_engine, table, batch_size):
    """Copy one table inside a single transaction. Rolls back on any failure.

    Returns the number of rows inserted. Never prints row contents.
    """
    inserted = 0
    ins = table.insert()
    # One controlled transaction for the whole table: begin() commits on success
    # and rolls back automatically if the block raises.
    with target_engine.begin() as conn:
        for batch in _read_batches(source_engine, table, batch_size):
            if batch:
                conn.execute(ins, batch)
                inserted += len(batch)
    return inserted


# --------------------------------------------------------------------------- #
# Validation (Phase 8)
# --------------------------------------------------------------------------- #

def _canonical(value) -> str:
    """Deterministic, value-preserving serialization for digests (not printed)."""
    if value is None:
        return "\x00NULL"
    if isinstance(value, bool):
        return "B1" if value else "B0"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "X" + bytes(value).hex()
    if isinstance(value, (datetime, date, time)):
        return "T" + value.isoformat()
    if isinstance(value, Decimal):
        return "D" + format(value, "f")
    return "S" + str(value)


def pk_columns(table):
    return [c.name for c in table.primary_key.columns]


def _pk_digest_and_bounds(engine, table):
    """Return (count, sha256 of sorted PK tuples, min_pk, max_pk-or-None)."""
    pks = pk_columns(table)
    cols = [table.c[name] for name in pks]
    tuples = []
    with engine.connect() as conn:
        for row in conn.execute(select(*cols)):
            tuples.append(tuple(row))
    tuples.sort(key=lambda t: [_canonical(v) for v in t])
    h = hashlib.sha256()
    for t in tuples:
        h.update("|".join(_canonical(v) for v in t).encode("utf-8"))
        h.update(b"\n")
    minv = maxv = None
    if len(pks) == 1 and tuples:
        vals = [t[0] for t in tuples]
        try:
            minv, maxv = min(vals), max(vals)
        except TypeError:
            minv = maxv = None
    return len(tuples), h.hexdigest(), minv, maxv


def _content_digest(engine, table):
    """sha256 over ALL columns of ALL rows, ordered by PK (value-preserving)."""
    pks = pk_columns(table)
    colnames = list(table.columns.keys())
    ordering = [table.c[name] for name in pks] or [table.c[colnames[0]]]
    h = hashlib.sha256()
    with engine.connect() as conn:
        stmt = select(*[table.c[n] for n in colnames]).order_by(*ordering)
        for row in conn.execute(stmt):
            m = row._mapping
            line = "|".join(_canonical(m[n]) for n in colnames)
            h.update(line.encode("utf-8"))
            h.update(b"\n")
    return h.hexdigest()


def _null_counts(engine, table):
    counts = {}
    with engine.connect() as conn:
        total = conn.execute(select(func.count()).select_from(table)).scalar() or 0
        for col in table.columns:
            nonnull = conn.execute(
                select(func.count(col)).select_from(table)
            ).scalar() or 0
            counts[col.name] = int(total) - int(nonnull)
    return counts


def fk_orphan_count(engine, table):
    """Total rows whose (non-null) FK value has no matching parent PK."""
    orphans = 0
    with engine.connect() as conn:
        for fk in table.foreign_keys:
            child = fk.parent          # column in this table
            parent = fk.column         # referenced parent column
            stmt = (
                select(func.count())
                .select_from(table)
                .where(child.isnot(None))
                .where(~child.in_(select(parent)))
            )
            orphans += int(conn.execute(stmt).scalar() or 0)
    return orphans


def validate(source_engine, target_engine, metadata):
    """Compare every application table. Returns (rows, all_ok).

    ``rows`` is a list of per-table result dicts suitable for the summary table.
    """
    src_insp = inspect(source_engine)
    tgt_insp = inspect(target_engine)
    results = []
    all_ok = True

    for tbl in dependency_order(metadata):
        name = tbl.name
        s_count, s_digest, s_min, s_max = _pk_digest_and_bounds(source_engine, tbl)
        t_count, t_digest, t_min, t_max = _pk_digest_and_bounds(target_engine, tbl)

        # PK definitions from both live schemas
        s_pk = src_insp.get_pk_constraint(name).get("constrained_columns", [])
        t_pk = tgt_insp.get_pk_constraint(name).get("constrained_columns", [])
        pk_def_match = list(s_pk) == list(t_pk) == pk_columns(tbl)
        pk_set_match = (s_count == t_count) and (s_digest == t_digest)

        # Column inventory (both must contain every model column)
        s_cols = {c["name"] for c in src_insp.get_columns(name)}
        t_cols = {c["name"] for c in tgt_insp.get_columns(name)}
        model_cols = set(tbl.columns.keys())
        cols_ok = model_cols <= s_cols and model_cols <= t_cols

        # NULL counts per column
        s_nulls = _null_counts(source_engine, tbl)
        t_nulls = _null_counts(target_engine, tbl)
        nulls_match = s_nulls == t_nulls

        # FK orphans on the target (and source, for reference)
        t_orphans = fk_orphan_count(target_engine, tbl)
        s_orphans = fk_orphan_count(source_engine, tbl)

        # Full content digest (catches any value/Unicode difference)
        content_match = _content_digest(source_engine, tbl) == \
            _content_digest(target_engine, tbl)

        ok = (
            s_count == t_count
            and pk_def_match
            and pk_set_match
            and cols_ok
            and nulls_match
            and t_orphans == 0
            and s_orphans == 0
            and content_match
        )
        all_ok = all_ok and ok
        results.append(
            {
                "table": name,
                "source": s_count,
                "target": t_count,
                "pk_match": pk_def_match and pk_set_match,
                "nulls_match": nulls_match,
                "fk_orphans": t_orphans,
                "cols_ok": cols_ok,
                "content_match": content_match,
                "status": "OK" if ok else "FAIL",
            }
        )
    return results, all_ok


def print_validation_summary(results):
    log("")
    log("TABLE                         | SOURCE | TARGET | PK MATCH | NULLS MATCH | FK ORPHANS | STATUS")
    log("-" * 100)
    for r in results:
        log(
            f"{r['table']:<29} | {r['source']:>6} | {r['target']:>6} | "
            f"{str(r['pk_match']):<8} | {str(r['nulls_match']):<11} | "
            f"{r['fk_orphans']:>10} | {r['status']}"
        )


# --------------------------------------------------------------------------- #
# Modes
# --------------------------------------------------------------------------- #

def _require_env():
    src = os.getenv("SQLITE_SOURCE_URL")
    tgt = os.getenv("MYSQL_TARGET_URL")
    missing = [n for n, v in (("SQLITE_SOURCE_URL", src),
                              ("MYSQL_TARGET_URL", tgt)) if not v]
    if missing:
        log(f"ERROR: missing required environment variable(s): {', '.join(missing)}")
        return None, None
    return src, tgt


def _print_connection_banner(source_url, target_url):
    log("Source: " + sanitize_url(source_url))
    log("Target: " + sanitize_url(target_url))


def run_dry_run(source_url, target_url, metadata, batch_size):
    _print_connection_banner(source_url, target_url)
    source_engine = build_engine(source_url)
    target_engine = build_engine(target_url)

    checks, safe = preflight(source_engine, target_engine, source_url, target_url,
                             metadata, require_empty_target=True)

    log("\n== Safety checks ==")
    for name, ok, detail in checks:
        log(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))

    # Inventory & exclusions
    model_tables = sorted(t.name for t in application_tables(metadata))
    log("\n== Table inventory (application, migrated) ==")
    log("  " + ", ".join(model_tables))
    log("== Explicitly excluded ==")
    log("  " + ", ".join(sorted(EXCLUDED_TABLES)) + " (+ SQLite internal tables)")

    # Dependency order
    order = dependency_order(metadata)
    log("\n== Resolved insert order (parents first) ==")
    for i, t in enumerate(order, 1):
        log(f"  {i:>2}. {t.name}")

    # Row counts (source)
    log("\n== Source row counts ==")
    total = 0
    for t in order:
        try:
            c = table_row_count(source_engine, t)
        except Exception as exc:  # noqa: BLE001
            c = -1
            log(f"  {t.name:<29} <count failed: {type(exc).__name__}>")
            continue
        total += c
        log(f"  {t.name:<29} {c}")
    log(f"  {'TOTAL':<29} {total}")

    # Type / length findings (needs target column types where possible)
    log("\n== Type & length findings (source max vs target capacity) ==")
    length_unsafe = False
    try:
        tgt_insp = inspect(target_engine)
        available = set(tgt_insp.get_table_names())
    except Exception:  # noqa: BLE001
        tgt_insp = None
        available = set()
    for t in order:
        target_types = {}
        if tgt_insp is not None and t.name in available:
            for col in tgt_insp.get_columns(t.name):
                target_types[col["name"]] = col["type"]
        try:
            findings = scan_length_overflows(source_engine, t, target_types)
        except Exception as exc:  # noqa: BLE001
            log(f"  {t.name}: <scan failed: {type(exc).__name__}>")
            continue
        for f in findings:
            if f["overflow"] or f["max_source"] > 0:
                flag = "OVERFLOW" if f["overflow"] else "ok"
                if f["overflow"]:
                    length_unsafe = True
                log(f"  {f['table']}.{f['column']}: max={f['max_source']} "
                    f"{f['unit']} / cap={f['capacity']} -> {flag}")

    # AUTO_INCREMENT
    log("\n== Tables requiring AUTO_INCREMENT reseed ==")
    for tbl, pk in autoincrement_tables(metadata):
        log(f"  {tbl.name} (pk={pk})")

    overall_safe = safe and not length_unsafe
    log("\n== Execution safety ==")
    log(f"  SAFE TO EXECUTE: {'YES' if overall_safe else 'NO'}")
    return EXIT_OK if overall_safe else EXIT_UNSAFE


def run_execute(source_url, target_url, metadata, batch_size):
    _print_connection_banner(source_url, target_url)
    source_engine = build_engine(source_url)
    target_engine = build_engine(target_url)

    checks, safe = preflight(source_engine, target_engine, source_url, target_url,
                             metadata, require_empty_target=True)
    log("\n== Safety checks ==")
    for name, ok, detail in checks:
        log(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not safe:
        log("\nABORT: preflight failed; no data was written.")
        return EXIT_UNSAFE

    # Detect partial state defensively (preflight already requires empty target).
    order = dependency_order(metadata)
    log("\n== Copying data (parents first) ==")
    total = 0
    for t in order:
        try:
            n = copy_table(source_engine, target_engine, t, batch_size)
        except Exception as exc:  # noqa: BLE001
            log(f"  {t.name:<29} FAILED ({type(exc).__name__}); this table rolled back.")
            log("\nABORT: migration stopped on first failure. Target now holds a "
                "PARTIAL copy of earlier tables.")
            log("Cleanup guidance: investigate the failing table, then either drop "
                "and re-create the MySQL schema with `flask db upgrade` on a fresh "
                "empty database, or manually DELETE the rows written so far. This "
                "tool will NOT auto-truncate. Re-run --execute only against an "
                "empty target.")
            return EXIT_UNSAFE
        total += n
        log(f"  {t.name:<29} {n} rows")
    log(f"  {'TOTAL':<29} {total} rows")

    log("\n== Reseeding AUTO_INCREMENT ==")
    for name, nxt in reseed_autoincrements(target_engine, metadata):
        log(f"  {name:<29} next={nxt}")

    log("\n== Post-execute validation ==")
    results, ok = validate(source_engine, target_engine, metadata)
    print_validation_summary(results)
    log(f"\nVALIDATION: {'PASS' if ok else 'FAIL'}")
    return EXIT_OK if ok else EXIT_UNSAFE


def run_validate_only(source_url, target_url, metadata, batch_size):
    _print_connection_banner(source_url, target_url)
    source_engine = build_engine(source_url)
    target_engine = build_engine(target_url)

    checks, safe = preflight(source_engine, target_engine, source_url, target_url,
                             metadata, require_empty_target=False)
    log("\n== Safety checks ==")
    for name, ok, detail in checks:
        log(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))

    results, ok = validate(source_engine, target_engine, metadata)
    print_validation_summary(results)
    # Alembic revision equality is part of preflight; fold it into the verdict.
    revisions_ok = all(
        o for (n, o, _d) in checks if "alembic revision" in n
    )
    verdict = ok and revisions_ok
    log(f"\nVALIDATION: {'PASS' if verdict else 'FAIL'}")
    return EXIT_OK if verdict else EXIT_UNSAFE


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser():
    p = argparse.ArgumentParser(
        prog="migrate_sqlite_to_mysql",
        description="One-time SQLite -> MySQL data migration (CoachHub Hockey).",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", dest="dry_run", action="store_true",
                      help="Inspect only; no writes; nonzero exit if unsafe.")
    mode.add_argument("--execute", action="store_true",
                      help="Copy data (refuses if any target app table is non-empty).")
    mode.add_argument("--validate-only", dest="validate_only", action="store_true",
                      help="Compare source vs target; no writes.")
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                   help=f"Insert batch size (default {DEFAULT_BATCH_SIZE}).")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    source_url, target_url = _require_env()
    if not source_url:
        return EXIT_USAGE

    metadata = load_metadata()
    if args.dry_run:
        return run_dry_run(source_url, target_url, metadata, args.batch_size)
    if args.execute:
        return run_execute(source_url, target_url, metadata, args.batch_size)
    return run_validate_only(source_url, target_url, metadata, args.batch_size)


if __name__ == "__main__":
    sys.exit(main())
