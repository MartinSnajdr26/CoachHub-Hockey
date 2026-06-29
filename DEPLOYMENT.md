# Deployment — CoachHub Hockey (PythonAnywhere)

Production-ready deployment notes. The app is a Flask + SQLite application that
runs "team-only" (team-key login, no user accounts/SMTP).

## 1. Requirements
- Python 3.10+ (developed/tested on 3.12)
- Dependencies: `pip install -r requirements.txt`
- WSGI application object: **`coach.app:app`** (`app = create_app()` is built at import time)

## 2. Required environment variables (production)
Set these in the **`.env`** file at the repo root (see `.env.example`). The app
**refuses to boot** in production if the first two are missing or left at the
development default:

| Variable | Required | Purpose |
|---|---|---|
| `APP_ENV` | yes | Set to `production` (anything not dev/development/local). |
| `SECRET_KEY` | yes | Signs session cookies. `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `ADMIN_SECRET_KEY` | yes | Owner-admin login secret for `/owner`. |
| `DB_URL` | recommended | e.g. `sqlite:////home/<user>/coachhub/data/prod.db` (absolute). |
| `TERMS_VERSION` | optional | Consent versioning (default `v1.0`). |

In development (`APP_ENV=dev`) `SECRET_KEY`/`ADMIN_SECRET_KEY` may be omitted; a
temporary owner secret is auto-generated and printed to the console.

## 3. PythonAnywhere setup
1. **Upload / clone** the repo (e.g. to `/home/<user>/coachhub`). Do **not** upload
   `.env`, `dev.db`, `TrailQuest/`, or `coach/static/uploads/` (all git-ignored).
2. **Virtualenv**: create one and `pip install -r requirements.txt`.
3. **`.env`**: create it at the repo root with the variables above (`APP_ENV=production`).
4. **Web tab → WSGI configuration file**: point it at the app:
   ```python
   import os, sys
   path = '/home/<user>/coachhub'        # repo root (contains coach/, migrations/, .env)
   if path not in sys.path:
       sys.path.insert(0, path)
   from coach.app import app as application
   ```
   Set the **working directory** to the repo root so `.env` (loaded from the repo
   root) and the SQLite relative path resolve correctly.
5. **Static files mapping**: URL `/static/` → `/home/<user>/coachhub/coach/static`.
   (Flask also serves it, but PythonAnywhere's static mapping is faster.)
6. **HTTPS**: enable "Force HTTPS". Required for the PWA service worker / install.
7. **Database migrations** (from the repo root, venv active):
   ```bash
   export FLASK_APP=coach/app.py
   flask db upgrade           # creates/updates all tables to the single head
   ```
   Migrations apply cleanly from an empty DB **and** from an existing one.
   Do **not** rely on `create_all()` in production (it only runs in dev).
8. **Reload** the web app.

## 4. First run
- **Create the first team**: open the site → `/team/auth` → "Create team". You get a
  coach key and a player key. Share the player key with players; keep the coach key.
- **Owner admin**: go to `/owner/login` and enter `ADMIN_SECRET_KEY`. The owner area
  (`/owner`) exposes health, integrations and diagnostics. See `coach/OWNER_ADMIN.md`.

## 5. PWA notes
- Manifest: `/static/manifest.webmanifest`; service worker served at root scope via
  `/sw.js`; offline page `/static/offline.html`; icons `icon-192/512(-maskable).png`.
- The service worker is **network-first for navigations** and only caches non-sensitive
  static assets — authenticated HTML, POSTs and team data are never cached.
- Install ("Add to Home Screen") requires HTTPS; Chromium shows a subtle in-app prompt.

## 6. Known limitations / operations
- **Rate limiting** uses in-memory storage (Flask-Limiter) — fine for a single web
  worker. For multiple workers, configure a Redis backend (`redis` is already a dep).
- **SQLite**: single-file DB; back it up by copying the DB file. For higher concurrency,
  migrate `DB_URL` to Postgres/MySQL (SQLAlchemy-compatible; re-run `flask db upgrade`).
- **Uploads/exports** live under `coach/static/uploads/` and `coach/protected_exports/`
  (git-ignored); ensure the web worker can write to them. Exports auto-clean after 14 days.

## 7. Running tests
```bash
pip install pytest
python -m pytest coach/tests/ -q
```
Tests are isolated to an in-memory SQLite DB and never touch `coach/dev.db`.
