# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CoachHub Hockey — a Flask app for hockey coaches/players: roster, line formations,
drills, training calendar, attendance, team cash (pokladna), and PDF exports. Runs
in **team-only mode**: no user accounts or passwords. Access is via per-team coach/
player keys. UI strings are Czech.

## Current phase — PWA and mobile UI only

The application is feature-complete.

Current work is limited to:

- mobile-only UI improvements
- PWA installability and offline fallback
- service-worker cache correctness
- mobile regressions
- production-safe deployment preparation

Do not add new product features unless explicitly requested.

### Desktop freeze

Desktop above 768px is frozen.

For mobile tasks:

- do not alter existing desktop markup
- do not modify protected desktop CSS
- do not change desktop workflows or navigation
- prefer additive mobile-only partials in `coach/templates/mobile/`
- prefer `coach/static/mobile.css` and isolated mobile JavaScript
- mobile-only DOM must be hidden by default on desktop
- verify desktop at 1280, 1440, and 1920px before declaring completion

Protected desktop stylesheets must not be changed for mobile-only work:

- `coach/static/style.css`
- `coach/static/lines.css`
- `coach/static/roster.css`
- `coach/static/help.css`

### Approved mobile screens

Do not broadly redesign approved mobile screens unless explicitly requested:

- Player Attendance
- Team Attendance
- Pokladna
- Dashboard
- Players
- Nástěnka
- Soupiska
- Settings after approval

### PWA privacy rules

The service worker must never cache:

- authenticated HTML
- session-specific pages
- attendance or payment data
- owner/admin pages
- POST responses
- private API responses

It may cache only non-sensitive static assets, the manifest, icons, and offline fallback.

Navigations remain network-first.

When cached static assets change, assess whether the service-worker cache version must be bumped.

### Database and deployment safety

For CSS, JavaScript, template, manifest, icon, or service-worker-only changes:

- do not create migrations
- do not run `flask db upgrade`
- do not run `db.create_all()`
- do not modify any database

Never commit or push unless explicitly instructed.

Before completion:

1. run focused tests
2. run the full test suite
3. validate every changed JavaScript file with `node --check`
4. validate the manifest when changed
5. confirm no database file was modified
6. report anything that could not be verified to the end of the claude.md

## Repository layout (important)

The Python package is `coach`, imported as `coach.app`, `coach.models`, etc. **The
repo root is the parent directory** (`/home/martin-snajdr/python`), which holds
`coach/`, `migrations/`, and `.env`. Always run commands from the repo root, not
from inside `coach/`.

```
<repo root>/          # contains .env, migrations/, requirements.txt
  coach/              # the Flask package
```

## Commands

Run everything from the **repo root** with the venv active (`source .venv/bin/activate`).

- Run the app (dev): `python3 -m coach.app` (serves on http://127.0.0.1:5000)
  - or `export FLASK_APP=coach.app:app && flask run`
- Run all tests: `python -m pytest coach/tests/ -q`
- Run a single test file: `python -m pytest coach/tests/test_lines.py -q`
- Run a single test: `python -m pytest coach/tests/test_lines.py::LinesTest::<method> -q`
- DB migrations (prod / schema changes): `export FLASK_APP=coach/app.py && flask db upgrade`
  (migrations dir is `migrations/` at repo root; single Alembic head)

There is no lint/format config checked in. Dependencies: `pip install -r requirements.txt`
(the repo-root `requirements.txt` is the one used).

## Database

- Dev uses SQLite `coach/dev.db` (set by `.env` `DB_URL=sqlite:///coach/dev.db`).
- **Tests must never touch `dev.db`.** `coach/tests/conftest.py` rebinds the
  SQLAlchemy engine to `:memory:` before any test runs and hard-asserts the binding
  per test. Test classes still set `SQLALCHEMY_DATABASE_URI='sqlite:///:memory:'` in
  `setUp` and call `db.drop_all(); db.create_all()` — do not remove the conftest
  guard or run tests in a way that bypasses it.
- Dev auto-creates tables (`db.create_all()` on `__main__`, plus a `before_request`
  hook `create_missing_dev_tables`). **Production uses Alembic only** — never rely on
  `create_all()` there.

## Architecture

`coach/app.py` builds the app at import time (`app = create_app()`), so the WSGI
object is `coach.app:app`. It wires extensions, security hooks, context processors,
registers blueprints, and adds **top-level endpoint aliases** (e.g. `/players`,
`/lines`, `/drill/...`) that map short URLs to blueprint views — when adding routes,
check the alias table in `create_app()` so you don't shadow or duplicate one.

Layered structure:
- `blueprints/` — request handlers grouped by feature (calendar, players, roster,
  lines, drills, attendance, pokladna, communication, settings, teamauth, owner,
  admin, files, legal, public).
- `models/__init__.py` — all SQLAlchemy models in one file. Nearly every row carries
  a nullable `team_id`; **always scope queries by the current `team_id`** for tenant
  isolation.
- `services/` — integration and business logic that must NOT live in route handlers
  (keys, exports, retention, tymuj, league/*, attendance_import/stats, recurrence,
  url_safety, db_state, owner_admin, logging).
- `extensions.py` — lazy singletons: `db`, `migrate`, `login_manager`, `bcrypt`,
  `csrf`, `limiter`.
- `context.py` / `security.py` — context processors (brand colors, nav) and security
  hooks (CSP nonce, headers, the `require_approval` team-session gate).

### Auth (team-key based)
- Each team has one active coach key and one active player key, hashed with scrypt
  (`services/keys`), shown once on creation/rotation.
- Session keys: `team_id`, `team_role`, `team_login`. `security.require_approval`
  redirects anything without a team session to `/team/auth` (allowing only static,
  `/owner*`, and a few public/legal paths).
- Decorators (`auth_utils.py`, re-exported from `app.py`): `team_login_required`
  gates team pages; `coach_required` gates mutating coach actions.
- Flask-Login is initialized only for template compatibility (no-op loaders); real
  auth is the team session.
- `/owner` is a separate owner-admin area gated by `ADMIN_SECRET_KEY` (session key
  `owner_admin`).

### Integrations & cache rule
Route rendering reads **local/cached state only**; external network calls happen
only in explicit refresh actions (settings test/refresh buttons). Follow this for
any new integration (see `ARCHITECTURE.md` "Adding Future Integrations").
- Týmuj: only the ICS URL is stored on `Team.tymuj_ics_url`; data fetched only on
  explicit actions, cached in `AuditEvent(event='tymuj.cache')`.
- League: config + cached data in `LeagueIntegration`; dashboard uses
  `league.service.get_view()`, never fetches.
- WhatsApp: client-side only (`static/wa.js`); no server-side API calls.

### Timezone convention
DB stores naive UTC (`datetime.utcnow`). User-facing datetimes are formatted to
Europe/Prague via the Jinja `|prague` filter (defined in `app.py`). **Exception:**
coach-entered event day/time (`TrainingEvent.time`) are naive LOCAL strings and are
NOT passed through the filter.

### Mobile vs desktop (how it's wired)
Mobile is a separate presentation layer: mobile partials in
`templates/mobile/_*.html` are `{% include %}`d alongside the desktop markup and
shown only at ≤768px via CSS (`static/mobile.css`, `static/mobilenav.js`). For the
desktop-freeze rules and the verification checklist, see
[Current phase — PWA and mobile UI only](#current-phase--pwa-and-mobile-ui-only).

## Exports & PWA
- PDF exports are written to `coach/protected_exports/` (outside `/static`),
  downloaded through the `files` blueprint with team-ownership checks, and
  auto-pruned after 14 days.
- PWA: manifest at `/static/manifest.webmanifest`; service worker served at root
  scope via `/sw.js` (route in `app.py`); network-first for navigations, never
  caches authenticated HTML.

## Config (.env at repo root, see `.env.example`)
`APP_ENV` (`dev`/`production`), `SECRET_KEY`, `ADMIN_SECRET_KEY`, `DB_URL`,
`TERMS_VERSION`, `SESSION_LIFETIME_DAYS`. In production the app **refuses to boot**
if `SECRET_KEY`/`ADMIN_SECRET_KEY` are missing or left at the dev default. Dev
relaxes secure cookies and auto-generates a temporary owner secret.

See also `ARCHITECTURE.md`, `DEPLOYMENT.md` (PythonAnywhere), and `OWNER_ADMIN.md`.
