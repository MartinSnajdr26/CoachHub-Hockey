# Production Performance & Concurrency Audit — CoachHub Hockey

Date: 2026-07-20
Scope: PythonAnywhere (single web worker) + SQLite. Read-only audit of the
current code, followed by small, production-safe fixes. No redesign, no feature
removal, no DB migration.

## Executive summary

The application is already **well-architected for a cached read path**: normal
page loads do **not** perform live external HTTP calls, and external refreshes
parse before they write (no network call inside an open write transaction).
`app.run()` is correctly guarded. The freezes/errors under concurrency are
explained mostly by a few concrete gaps, fixed in this pass:

1. **SQLite has no busy timeout** → concurrent writers raise `database is locked`
   immediately instead of waiting. This is the most likely cause of the
   "errors when saving / freezes with multiple users". **Fixed (Phase 3).**
2. **No connection pre-ping** → a pooled connection that went stale while the
   PythonAnywhere worker idled can raise on the next request. **Fixed (Phase 3).**
3. **Calendar Prev/Today/Next AJAX has no cancellation** → rapid clicks pile
   overlapping full-dashboard requests onto the single worker and an older
   response can overwrite a newer one. **Fixed (Phase 6).**
4. **Forms have no double-submit guard** → double-clicks/refresh create duplicate
   rows and duplicate worker-blocking requests. **Fixed (Phase 5, client + a
   narrow server-side dedup for single manual event creation).**
5. **No request timing / slow-request logging** → impossible to see which
   endpoint blocks the worker. **Fixed (Phase 2).**
6. **Unhandled exceptions log no traceback to the server log** — the catch-all
   `@app.errorhandler(Exception)` returns a 500 page, so Flask skips its own
   traceback logging; only a short DB audit row is written. **Fixed (Phase 2:
   add `logger.exception`).**

Everything else audited below is already correct and is covered by new
regression tests rather than code changes.

---

## Findings

### A. Blocking work / worker contention

| File | Function/route | Issue | Impact | Fix | When |
|---|---|---|---|---|---|
| `templates/home.html` (calendar `swap()`) | dashboard calendar Prev/Today/Next | `fetch()` with no `AbortController`; rapid clicks issue overlapping requests; older response can overwrite newer | On a single worker, overlapping full-dashboard reloads queue up → perceived freeze; UI can flicker to an out-of-date month | Add one component-scoped `AbortController`; abort previous before next; ignore `AbortError` | **Now** |
| `context.py` | `inject_notifications` | ~4–6 indexed queries on **every** authenticated page (incl. each calendar AJAX swap) | Small fixed per-request overhead; not a lock risk | Left as-is (indexed, cheap); documented for a later micro-opt to avoid behavior change | Later |
| `blueprints/calendar.py` | `home` | Assembles many widgets (events, attendance, league view, tymuj cache, messages) per load | Heavier GET, but all **local/cached** reads | No change (correct by design) | — |

### B. SQLite write-lock risk / unnecessary writes

| File | Function/route | Issue | Impact | Fix | When |
|---|---|---|---|---|---|
| `app.py` | engine config | No `connect_args={'timeout': …}` → SQLite `busy_timeout` is the default (~5 s in some builds, 0 via SQLAlchemy) so concurrent writers fail fast with `database is locked` | Save errors / 500s when two users write at once | Add `SQLALCHEMY_ENGINE_OPTIONS` with `connect_args={'timeout': 30}` **only for sqlite** | **Now** |
| `app.py` | engine config | No `pool_pre_ping` | Stale pooled connection after idle can raise | Add `pool_pre_ping=True` | **Now** |
| `services/logging.py` | `log_event` | Writes an `AuditEvent` row (INSERT+COMMIT) on many actions incl. every handled exception/rate-limit | Extra small writes; each is its own short txn (fine) but adds write pressure under load | No change now (audit trail is a feature); noted for future move to async/table batching | Later |
| `blueprints/players.py` `import_tymuj`, `blueprints/calendar.py` `calendar_add` (recurring) | bulk insert | Add-in-loop then **single commit** after the loop (bounded by `MAX_OCCURRENCES`) | Correct — no commit-in-loop | No change | — |
| `services/retention.py` | `prune_*` | commit inside a `for` loop | Only runs from CLI/maintenance, not a request path | No change (acceptable for a batch job) | — |

### C. External HTTP during page loads

| File | Function | Issue | Impact | Fix | When |
|---|---|---|---|---|---|
| `services/league/service.py` | `get_view` | **Read-only**, never fetches; `maybe_auto_refresh` exists but has **no callers** | None — dashboard uses cached data | No change; add regression test asserting no fetch on dashboard load | **Now (test)** |
| `services/tymuj.py` | `get_cached_events` / `_cache_payload` | Read cached JSON only (memoized per request) | None on load | No change | — |
| `services/league/service.py` | `refresh` | Fetch+parse happen **between** commits, not inside an open write txn; has `TIMEOUT=10 s`; only reachable via explicit coach refresh (rate-limited by `MIN_MANUAL_SECONDS`) | Correct | No change | — |
| `services/tymuj.py` | `refresh_cache` | External fetch with `TIMEOUT=45 s`/`RETRY_TIMEOUT=60 s`; only on explicit refresh | Long, but off the page-load path | No change (documented; consider lowering timeout later) | Later |

### D. Duplicate submissions / overlapping requests

| File | Route | Issue | Impact | Fix | When |
|---|---|---|---|---|---|
| all POST forms | create/update actions | No client double-submit guard | Double-click / refresh → duplicate rows, duplicate worker-blocking requests | Reusable `app.js` submit guard (disable + "Ukládám…", bfcache-safe, opt-out via `data-no-busy`) | **Now** |
| `blueprints/calendar.py` | `calendar_add` (single, manual) | No server-side idempotency | A resubmitted POST can create an identical event even if the client guard is bypassed | Narrow dedup: skip insert when an identical `(team_id, day, time, title, kind, source='coachhub_manual')` row already exists; still redirect success | **Now** |
| `templates/home.html` | calendar nav | Overlapping AJAX (see A) | see A | see A | **Now** |

### E. Transactions, rollback, session lifecycle

| File | Observation | Status |
|---|---|---|
| `extensions.py` (Flask-SQLAlchemy 3.1.1) | `db.session` is a scoped session; Flask-SQLAlchemy registers a `teardown_appcontext` that calls `session.remove()` (which rolls back any pending txn) after every request | Correct — session cleanup already handled |
| `context.py`, `services/logging.py`, `blueprints/*` | `except` blocks call `db.session.rollback()` before continuing | Correct |
| `services/league/service.py` `refresh` | rollback on failure, then records `last_error` in a fresh short txn | Correct |

### F. WSGI / dev server

| File | Observation | Status |
|---|---|---|
| `app.py` | `app.run()` is only under `if __name__ == "__main__":`; WSGI object is `coach.app:app` (built via `create_app()` at import) | Correct |
| repo | No PythonAnywhere WSGI file is committed (only in unrelated venvs) → not modified. Expected import documented below | Correct |

**Expected PythonAnywhere WSGI file** (on the server, not in the repo):

```python
import sys
project_root = '/home/<user>/python'      # dir that contains the `coach/` package and `.env`
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from coach.app import app as application   # create_app() already ran at import; NO app.run()
```

---

## Fixes applied in this pass (summary)

- `app.py`: `SQLALCHEMY_ENGINE_OPTIONS` (pool_pre_ping + sqlite-only `connect_args={'timeout':30}`); `logger.exception` in the catch-all error handler.
- `services/request_timing.py` (new) + wired in `create_app()`: per-request timing, slow-request warning (`SLOW_REQUEST_THRESHOLD_MS`, default 1000), query count, safe fields only.
- `templates/home.html`: `AbortController` for calendar navigation.
- `static/app.js`: reusable double-submit guard.
- `blueprints/calendar.py`: narrow server-side dedup for single manual event creation.

## Intentionally not changed

- No WAL (explicitly unsafe assumption on PythonAnywhere's shared/NFS storage).
- No Celery/Redis/background worker.
- No PostgreSQL/MySQL migration (see `database_migration_readiness.md`).
- `inject_notifications` query fan-out and Týmuj refresh timeout left as-is to avoid behavior changes.
