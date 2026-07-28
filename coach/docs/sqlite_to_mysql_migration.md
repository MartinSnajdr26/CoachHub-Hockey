# SQLite → MySQL migration (CoachHub Hockey)

A one-time copy of production **row data** from the PythonAnywhere SQLite file
into an already-provisioned MySQL 8.0 (`utf8mb4` / `utf8mb4_unicode_ci`) schema.

- Utility: `coach/scripts/migrate_sqlite_to_mysql.py`
- Tests: `coach/tests/test_migrate_sqlite_to_mysql.py` (offline; no MySQL needed)
- Modes (exactly one required): `--dry-run`, `--execute`, `--validate-only`

> The schema on MySQL is created **only** by Alembic (`flask db upgrade`), never
> by this tool. This tool copies data into that empty schema and never runs DDL,
> `create_all`, truncate, overwrite, or merge. It never migrates `alembic_version`
> or the obsolete `audit_log` table, and never prints credentials or row values.

## What is migrated

17 application tables (from live SQLAlchemy metadata):

```
attendance_entry, attendance_import, audit_event, drill, league_integration,
line_assignment, lineup_session, payment_period, payment_status, player,
roster, team, team_calendar_feed_token, team_key, team_login_attempt,
training_event, training_session
```

**Explicitly excluded:** `alembic_version` (schema bookkeeping), `audit_log`
(obsolete orphan, 0 rows, not in the models), and SQLite internal tables.

Resolved FK-safe insert order (parents first, deterministic):

```
 1 team               7 payment_period    13 training_session
 2 attendance_import  8 player             14 attendance_entry
 3 audit_event        9 team_calendar_feed_token  15 line_assignment
 4 drill             10 team_key           16 payment_status
 5 league_integration 11 team_login_attempt 17 roster
 6 lineup_session    12 training_event
```

## MySQL compatibility risks (found in this codebase)

| # | Risk | Handling |
|---|------|----------|
| 1 | **`TEXT` capacity.** `drill.image_data` / `drill.path_data` (base64 images), `league_integration.data_json`, `audit_event.meta`, `attendance_import.warnings`, `training_session.drill_ids` are `Text`. MySQL `TEXT` caps at 65,535 **bytes**; a large base64 image can overflow. | **Confirmed by the production dry run** (`drill.image_data` ≈ 381 KB, `drill.path_data` ≈ 117 KB). **Fixed:** both columns are now `MEDIUMTEXT` (≈ 16 MB) on MySQL via Alembic revision `e2f3a4b5c6d7` (plain `TEXT` on SQLite). Run `flask db upgrade` on the target **before** copying. `--dry-run` still scans source byte-lengths vs the **inspected** target capacity and reports `OVERFLOW`; any value above `MEDIUMTEXT` remains blocked. |
| 2 | **Collation case/accent folding.** `utf8mb4_unicode_ci` is case- and accent-insensitive; SQLite's default is binary (case-sensitive). Values distinct in SQLite (e.g. `Sparta` vs `sparta`) can collide on a UNIQUE index in MySQL (`team.name`, `team_calendar_feed_token.token`, `league_integration.team_id`). | A collision surfaces as a duplicate-key error during `--execute`, which rolls back that table and stops. If the pilot has such near-duplicates, resolve them in SQLite first (or use a `_bin` collation on those columns). |
| 3 | **Booleans.** SQLite stores `0/1`; MySQL uses `TINYINT(1)`. | Type-driven normalization coerces to Python `bool`; typed Core inserts store `0/1`. |
| 4 | **Datetimes / dates.** Stored as **naive UTC** strings in SQLite. | Read via typed columns and normalized to `datetime`/`date`; naive is preserved (MySQL `DATETIME` is tz-naive — do **not** switch to a tz type). |
| 5 | **NULL vs empty string.** **Found in production validation:** `training_event.source` was `NOT NULL` but the live SQLite data holds 42 legacy `NULL`s. MySQL's non-strict `sql_mode` silently coerced each inserted `NULL` → `''` (the type's implicit default), failing NULL/content validation. | **Fixed two ways:** (a) `training_event.source` is now **nullable** (Alembic `f3a4b5c6d7e8`) so `NULL` round-trips; (b) the utility forces **`STRICT_ALL_TABLES`** on the MySQL target, so any future `NULL`→`NOT NULL` (or truncation) **errors and rolls back** instead of silently coercing. The utility itself always inserts SQL `NULL` (never drops the key, never converts to `''`); `''` and `NULL` stay distinct. |
| 6 | **Reserved-ish identifiers** (`year`, `month`, `time`, `day`, `status`, `source`, `kind`, `event`, table `team_key`). | SQLAlchemy Core quotes identifiers; the schema was created by Alembic from the same metadata, so names already match. |
| 7 | **AUTO_INCREMENT continuation.** | After load, each integer PK's `AUTO_INCREMENT` is reseeded to `max(pk)+1`. |

Emoji/Czech/German/Japanese round-trip requires the target to be `utf8mb4`
(confirmed) — validation includes a full content digest that fails on any
byte-level difference.

---

# A. Local development and Git preparation

Run from the **repo root** (`/home/martin-snajdr/python`) with the venv active.
**Do not run the migration locally. Do not connect to production MySQL.**

1. **Review the generated files.**
   - `coach/scripts/migrate_sqlite_to_mysql.py`
   - `coach/tests/test_migrate_sqlite_to_mysql.py`
   - `coach/docs/sqlite_to_mysql_migration.md` (this file)
   - `requirements.txt` (adds `PyMySQL==1.1.1`)

2. **Run the focused tests:**
   ```bash
   python -m pytest coach/tests/test_migrate_sqlite_to_mysql.py -q
   ```

3. **Run the full suite:**
   ```bash
   python -m pytest coach/tests/ -q
   ```

4. **Commit locally** (only when you decide to):
   ```bash
   git add coach/scripts/ coach/tests/test_migrate_sqlite_to_mysql.py \
           coach/docs/sqlite_to_mysql_migration.md requirements.txt
   git commit -m "Add one-time SQLite->MySQL migration utility"
   ```

5. **Push to origin/main:**
   ```bash
   git push origin main
   ```

6. **Do not run the migration locally** — no `--execute`, no `--validate-only`
   against production, no `.env` changes, no DB writes.

---

# B. PythonAnywhere deployment and migration

All commands run in a **PythonAnywhere Bash console** (not the web app).

> **Run the utility with module syntax** — `python -m coach.scripts.migrate_sqlite_to_mysql …`.
> Direct file execution (`python coach/scripts/migrate_sqlite_to_mysql.py`) fails
> from the repo root with `ModuleNotFoundError: No module named 'coach'`.

### Required sequence (includes the Drill MEDIUMTEXT + NULL-fidelity fixes)

Current Alembic head: **`f3a4b5c6d7e8`** (adds `training_event.source` nullability
on top of the Drill `MEDIUMTEXT` widening).

1. `git pull origin main`
2. `pip install -r requirements.txt`
3. Set `MYSQL_TARGET_URL` (Section B.2).
4. **Recreate the target MySQL schema** (see box below) — required if any earlier
   migration run happened, because the old schema had `training_event.source
   NOT NULL` and may already hold coerced `''` values.
5. Upgrade **both** databases to the head:
   `DB_URL="$MYSQL_TARGET_URL" FLASK_APP=coach.app:app flask db upgrade`
   and `FLASK_APP=coach.app:app flask db upgrade` (source SQLite stamp).
6. Verify the head:
   `FLASK_APP=coach.app:app DB_URL="$MYSQL_TARGET_URL" flask db current` → `f3a4b5c6d7e8`.
7. Dry run: `python -m coach.scripts.migrate_sqlite_to_mysql --dry-run`.
8. Execute: `python -m coach.scripts.migrate_sqlite_to_mysql --execute`.
9. Validate: `python -m coach.scripts.migrate_sqlite_to_mysql --validate-only`.

Proceed to `--execute` only when the dry run shows no `OVERFLOW`, `SAFE TO
EXECUTE: YES`, and the target is empty.

> **⚠️ Recreate the target after the NULL fix.** Fidelity requires the target
> `training_event.source` to be **nullable**. Running `flask db upgrade` on a
> target that was *already migrated* under the old `NOT NULL` schema alters the
> column to nullable but does **not** repair already-coerced `''` values, and
> `--execute` refuses a non-empty target anyway. So start from a **fresh, empty**
> target:
>
> ```bash
> # Drop and recreate the application schema on MySQL, then rebuild via Alembic.
> # (Drops only the app tables + alembic_version — never the SQLite source.)
> DB_URL="$MYSQL_TARGET_URL" FLASK_APP=coach.app:app flask db downgrade base   # or DROP the tables
> DB_URL="$MYSQL_TARGET_URL" FLASK_APP=coach.app:app flask db upgrade          # -> f3a4b5c6d7e8
> ```
>
> If you prefer, drop and re-create the `martinsnajdr$coachhub` database (or its
> tables) directly, then `flask db upgrade`. The `training_event.source` column
> must end up **nullable** — confirm with `SHOW COLUMNS FROM training_event LIKE 'source';`
> (expect `Null = YES`).

The detailed steps follow.

## B.1 Pull and install

```bash
cd ~/coach
git status --short          # expect a clean tree before pulling
git pull origin main
source venv/bin/activate
```

Install dependencies **only after** the pull (brings in `PyMySQL`):

```bash
pip install -r requirements.txt
```

## B.2 Environment variables (never printed in full)

```bash
export SQLITE_SOURCE_URL='sqlite:////home/martinsnajdr/coach/instance/app.db'
```

Verify `MYSQL_TARGET_URL` exists **without printing it**:

```bash
python - <<'PY'
import os
print("MYSQL_TARGET_URL present:", bool(os.getenv("MYSQL_TARGET_URL")))
PY
```

If it prints `False`, reconstruct it **in the shell only** — never write the
password to the repo or `.env`. Use `read -s` so the password is not echoed or
saved to shell history, and escape the `$` in the database name:

```bash
read -rsp 'MySQL password: ' DBPASS; echo
export MYSQL_TARGET_URL="mysql+pymysql://martinsnajdr:${DBPASS}@martinsnajdr.mysql.eu.pythonanywhere-services.com/martinsnajdr\$coachhub?charset=utf8mb4"
unset DBPASS
```

Bring **both** databases to the current Alembic head `f3a4b5c6d7e8` (which widens
`drill.image_data` / `drill.path_data` to `MEDIUMTEXT` on MySQL — see risk #1).
The migration utility requires source **and** target to be at the same head.

Upgrade the **target MySQL** schema (widens the Drill columns in place; safe on
the empty pre-provisioned schema):

```bash
FLASK_APP=coach.app:app DB_URL="$MYSQL_TARGET_URL" flask db upgrade
FLASK_APP=coach.app:app DB_URL="$MYSQL_TARGET_URL" flask db current   # -> f3a4b5c6d7e8
```

Also advance the **source SQLite** stamp to the same head. On SQLite this
revision is a **no-op** (TEXT is unbounded) — it only updates `alembic_version`
so the utility's source/target revision check passes:

```bash
FLASK_APP=coach.app:app flask db upgrade                              # uses .env DB_URL (the SQLite source)
FLASK_APP=coach.app:app flask db current   # -> f3a4b5c6d7e8
```

> Setting `DB_URL` inline for the target command does **not** switch the running
> web app to MySQL — cutover is a separate, explicit step (Section C).

## B.3 Fresh backup (immediately before migrating)

Create a **consistent** SQLite snapshot with the online backup API, then verify
it (integrity, row counts, SHA-256):

```bash
python - <<'PY'
import sqlite3, hashlib, os, datetime
src = "/home/martinsnajdr/coach/instance/app.db"
outdir = "/home/martinsnajdr/coach/backups/mysql-migration"
os.makedirs(outdir, exist_ok=True)
ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
dst = f"{outdir}/app.db.{ts}.bak"

# Consistent online snapshot (safe even if the app is running).
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)

with sqlite3.connect(dst) as d:
    print("integrity_check:", d.execute("PRAGMA integrity_check").fetchone()[0])
    tables = [r[0] for r in d.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    print("row counts:")
    for t in tables:
        n = d.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        print(f"  {t}: {n}")

h = hashlib.sha256()
with open(dst, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
print("sha256:", h.hexdigest())
print("backup path:", dst)
PY
```

Record the printed backup path, SHA-256 and row counts.

## B.4 Dry run (no writes)

```bash
python -m coach.scripts.migrate_sqlite_to_mysql --dry-run
```

Review every safety check, the source row counts, the type/length findings and
`SAFE TO EXECUTE: YES`. The dry run performs **no writes**; you do **not** need
to block production writes for it — unless the script reports the source is
changing during inspection (counts shifting), in which case pause writes and
re-run. A non-zero exit means unsafe: stop and resolve the flagged item.

After the target upgrade (B.2, head `f3a4b5c6d7e8`), the previously-reported
`drill.image_data` / `drill.path_data` overflow findings must be gone — their
target capacity is now `MEDIUMTEXT` (16,777,215 bytes). If any `OVERFLOW` is
still reported, do **not** run `--execute`; the schema upgrade did not apply.

## B.5 Maintenance window and execution

Before `--execute`:

1. **Stop all writes.** Put the app into maintenance mode — on PythonAnywhere the
   simplest reliable way is to **disable the web app** (Web tab → *Disable*) or
   serve a static maintenance page — so no user request can write during the copy.
2. Keep the window **short** (this dataset is small — seconds).
3. Create **one final** SQLite backup (rerun B.3).
4. **Re-run the dry run** (B.4) and confirm `SAFE TO EXECUTE: YES`.
5. **Verify the target is empty** (the dry run's "target application tables are
   empty" check must be `PASS`).

Then execute:

```bash
python -m coach.scripts.migrate_sqlite_to_mysql --execute
```

`--execute` refuses to run if any target application table already has rows.
It copies in dependency order (one transaction per table, rollback-on-failure,
stop on first error), reseeds `AUTO_INCREMENT`, then runs validation
automatically.

Then run validation explicitly:

```bash
python -m coach.scripts.migrate_sqlite_to_mysql --validate-only
```

Both must end with `VALIDATION: PASS`. The summary line per table is:

```
TABLE | SOURCE | TARGET | PK MATCH | NULLS MATCH | FK ORPHANS | STATUS
```

### If `--execute` fails partway

It stops on the first failure; the failing table is rolled back but earlier
tables are already copied (a **partial** target). The tool will **not**
auto-truncate. To recover: investigate the failing table, then re-create a clean
empty schema — drop the MySQL application tables and re-run `flask db upgrade`
against the empty DB (or manually `DELETE` the rows written so far) — and only
then re-run `--execute` against the empty target.

---

# C. Production cutover

Only after `--validate-only` prints `VALIDATION: PASS`:

1. Set the production **`DB_URL`** (Web tab → *Environment variables*, or the
   WSGI/`.env` mechanism you use) to the MySQL URL:
   ```
   DB_URL=mysql+pymysql://martinsnajdr:PASSWORD@martinsnajdr.mysql.eu.pythonanywhere-services.com/martinsnajdr$coachhub?charset=utf8mb4
   ```
   Do **not** remove or overwrite the documented SQLite `SQLITE_SOURCE_URL` — keep
   it recorded for rollback.
2. **Reload** the web app (Web tab → *Reload*). Re-enable it if you disabled it.
3. Run **smoke tests** (below).

### Smoke tests (post-cutover)

- Public **welcome** page renders.
- **Team login** (coach key and player key).
- **Owner login** (`/owner/login`).
- **Dashboard** renders.
- **Attendance** view loads (player + team).
- **Drills** list + a drill detail.
- **Calendar** reads (month view + `.ics` feed).
- **Create** one controlled test record (e.g. a training event), **update** it,
  then **delete / clean it up**.
- **League cache** read (dashboard league panel; no external fetch).
- **PWA / service worker** unaffected (icons load, offline page still works).
- **Concurrency:** two browser sessions read/write at once (the reason for
  leaving SQLite) — no "database is locked" errors.

---

# D. Rollback

Immediate rollback (before or shortly after cutover, if smoke tests fail):

1. Restore the previous **`DB_URL`** to the SQLite URL:
   ```
   DB_URL=sqlite:////home/martinsnajdr/coach/instance/app.db
   ```
2. **Reload** the web app.
3. **Do not modify or delete MySQL data** during an immediate rollback — leave it
   intact for investigation.

> ⚠️ **Data-loss caveat:** any writes made through the app **after** cutover live
> only in MySQL. Rolling back to SQLite after such writes loses those changes
> unless you separately reconcile them back into SQLite. This is why the copy is
> done inside a short maintenance window with writes stopped — so the SQLite file
> stays a faithful rollback target.

---

# MySQL backup (target)

Take a logical dump of the MySQL database at any time (e.g. right after a
validated migration). Use a placeholder — `-p` prompts for the password so it is
never embedded or saved:

```bash
mysqldump --single-transaction --no-tablespaces \
  -h martinsnajdr.mysql.eu.pythonanywhere-services.com \
  -u martinsnajdr -p 'martinsnajdr$coachhub' \
  > ~/coach/backups/mysql-migration/coachhub-mysql-$(date +%Y%m%d-%H%M%S).sql
```

Restore (into an empty schema) if ever needed:

```bash
mysql -h martinsnajdr.mysql.eu.pythonanywhere-services.com \
  -u martinsnajdr -p 'martinsnajdr$coachhub' \
  < ~/coach/backups/mysql-migration/coachhub-mysql-YYYYMMDD-HHMMSS.sql
```

---

## Command reference

| Purpose | Command |
|---------|---------|
| Dry run (no writes) | `python -m coach.scripts.migrate_sqlite_to_mysql --dry-run` |
| Execute (empty target only) | `python -m coach.scripts.migrate_sqlite_to_mysql --execute` |
| Validate only | `python -m coach.scripts.migrate_sqlite_to_mysql --validate-only` |
| Custom batch size | `... --execute --batch-size 500` |

Required environment: `SQLITE_SOURCE_URL`, `MYSQL_TARGET_URL` (both must be set;
the script prints only sanitized connection details, never the password).
