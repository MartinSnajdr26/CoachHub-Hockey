from flask import Flask
import os
import io
from datetime import timedelta
from PIL import Image
import hashlib
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
 

app = Flask(__name__)

def create_app():
    """Build and configure the Flask application.
    Initializes extensions, security, context, blueprints and legacy endpoint aliases.
    Returns the configured app instance.
    """
    # Ensure extensions are bound (done earlier in module): db, migrate, login_manager, bcrypt, csrf, limiter
    # Security + context
    from coach.security import register_security
    register_security(app)
    from coach.context import register_context
    register_context(app)
    # Central per-request performance + slow-request logging (audit Phase 2).
    from coach.services.request_timing import register_request_timing
    register_request_timing(app)

    # ---- Prague-time DISPLAY filter (DST-safe) ----
    # DB stores timestamps as naive UTC (datetime.utcnow). User-facing displays
    # must show Europe/Prague. Event day/time entered by coaches are naive LOCAL
    # strings (TrainingEvent.time) and are NOT passed through this filter.
    import datetime as _dtmod
    try:
        from zoneinfo import ZoneInfo
        _PRAGUE_TZ = ZoneInfo("Europe/Prague")
    except Exception:
        _PRAGUE_TZ = None

    def _prague_fmt(dt, fmt='%d.%m.%Y %H:%M'):
        if not dt:
            return ''
        try:
            if getattr(dt, 'tzinfo', None) is None:        # naive -> assume UTC (storage convention)
                dt = dt.replace(tzinfo=_dtmod.timezone.utc)
            if _PRAGUE_TZ is not None:
                dt = dt.astimezone(_PRAGUE_TZ)
            return dt.strftime(fmt)
        except Exception:
            return ''
    app.jinja_env.filters['prague'] = _prague_fmt
    app.jinja_env.globals['now_prague'] = (
        lambda: (_dtmod.datetime.now(_dtmod.timezone.utc).astimezone(_PRAGUE_TZ)
                 if _PRAGUE_TZ else _dtmod.datetime.utcnow())
    )
    from coach.services.session_share import session_whatsapp_url as _session_wa_url
    app.jinja_env.globals['session_whatsapp_url'] = _session_wa_url

    # Blueprints registration (register individually and log failures)
    from importlib import import_module
    def _reg(mod_path: str, name: str):
        try:
            bp = import_module(mod_path).bp
            app.register_blueprint(bp)
        except Exception as e:
            try:
                app.logger.error('Failed to register blueprint %s (%s): %s', name, mod_path, e)
            except Exception:
                pass
    # Register team auth first so /team/auth is always available
    _reg('coach.blueprints.teamauth', 'teamauth')
    _reg('coach.blueprints.public', 'public')
    _reg('coach.blueprints.legal', 'legal')
    _reg('coach.blueprints.calendar', 'calendar')
    _reg('coach.blueprints.players', 'players')
    _reg('coach.blueprints.roster', 'roster')
    _reg('coach.blueprints.lines', 'lines')
    _reg('coach.blueprints.drills', 'drills')
    _reg('coach.blueprints.files', 'files')
    _reg('coach.blueprints.admin', 'admin')
    _reg('coach.blueprints.owner', 'owner')
    _reg('coach.blueprints.settings', 'settings')
    _reg('coach.blueprints.attendance', 'attendance')
    _reg('coach.blueprints.pokladna', 'pokladna')
    _reg('coach.blueprints.communication', 'communication')

    # Provide top-level endpoint aliases
    try:
        aliases = [
            ('/team/auth', 'team_auth', 'teamauth.team_auth', None),
            ('/team/login', 'team_login', 'teamauth.team_login', ['POST']),
            ('/team/logout', 'team_logout', 'teamauth.team_logout', None),
            ('/team/create', 'team_create', 'teamauth.team_create', ['POST']),
            ('/team/keys', 'team_keys', 'teamauth.team_keys', ['GET','POST']),
            ('/dochazka', 'dochazka', 'calendar.dochazka', ['GET','POST']),
            # Legal pages aliases
            ('/terms', 'terms', 'legal.terms', None),
            ('/privacy', 'privacy', 'legal.privacy', None),
            ('/about', 'about', 'legal.about', None),
            ('/terms/consent', 'terms_consent', 'legal.terms_consent', ['GET','POST']),
            ('/players', 'players', 'players.players', None),
            ('/add_player', 'add_player', 'players.add_player', ['POST']),
            ('/delete_player/<int:player_id>', 'delete_player', 'players.delete_player', ['POST']),
            ('/edit_player/<int:player_id>', 'edit_player', 'players.edit_player', ['GET','POST']),
            ('/roster', 'roster', 'roster.roster', ['GET','POST']),
            ('/delete_from_roster/<int:roster_id>', 'delete_from_roster', 'roster.delete_from_roster', ['POST']),
            ('/lines', 'lines', 'lines.lines', ['GET','POST']),
            ('/lines/export_pdf', 'export_lines_pdf', 'lines.export_lines_pdf', ['POST']),
            ('/lineup-sessions', 'lineup_sessions', 'lines.lineup_sessions', None),
            ('/lineup-sessions/delete/<int:sess_id>', 'delete_lineup_session', 'lines.delete_lineup_session', ['POST']),
            ('/drill/new', 'new_drill', 'drills.new_drill', None),
            ('/drill/save', 'save_drill', 'drills.save_drill', ['POST']),
            ('/drill/<int:drill_id>/edit', 'edit_drill', 'drills.edit_drill', None),
            ('/drill/<int:drill_id>/update', 'update_drill', 'drills.update_drill', ['POST']),
            ('/drills', 'drills', 'drills.drills', None),
            ('/drills/<category>', 'drills_by_category', 'drills.drills_by_category', None),
            ('/drill/<int:drill_id>', 'drill_detail', 'drills.drill_detail', None),
            ('/drill/delete/<int:drill_id>', 'delete_drill', 'drills.delete_drill', ['POST']),
            ('/drills/select', 'drills_select', 'drills.drills_select', None),
            ('/drills/export_pdf', 'export_drills_pdf', 'drills.export_drills_pdf', ['POST']),
            ('/drill-sessions', 'drill_sessions', 'drills.drill_sessions', None),
            ('/drill-sessions/delete/<int:sess_id>', 'delete_drill_session', 'drills.delete_drill_session', ['POST']),
            ('/drills/export_result', 'drills_export_result', 'drills.drills_export_result', None),
            ('/exports/<path:filename>', 'download_export', 'files.download_export', None),
            ('/admin/audit-log', 'audit_log', 'admin.audit_log', None),
            ('/settings', 'settings', 'settings.settings', ['GET','POST']),
            ('/team/members/action', 'team_members_action', 'settings.team_members_action', ['POST']),
            ('/app', 'home', 'calendar.home', None),
            ('/calendar/add', 'calendar_add', 'calendar.calendar_add', ['POST']),
            ('/calendar/update', 'calendar_update', 'calendar.calendar_update', ['POST']),
            ('/calendar/delete', 'calendar_delete', 'calendar.calendar_delete', ['POST'])
        ]
        # Build a set of existing (rule, endpoint) to avoid duplicates
        existing_rules = set((r.rule, r.endpoint) for r in app.url_map.iter_rules())
        for rule, endpoint, view_name, methods in aliases:
            view_func = app.view_functions.get(view_name)
            if not view_func:
                continue
            if (rule, endpoint) in existing_rules or endpoint in app.view_functions:
                continue
            if methods:
                app.add_url_rule(rule, endpoint=endpoint, view_func=view_func, methods=methods)
            else:
                app.add_url_rule(rule, endpoint=endpoint, view_func=view_func)
    except Exception:
        # In debug reloads, aliases may exist already
        pass

    # CLI: retention prune
    import click
    @app.cli.command('retention:prune')
    @click.option('--days', default=365, type=int, help='Delete users inactive for this many days')
    def retention_prune(days):
        """Prune inactive users and their data."""
        from coach.services.retention import prune_inactive_users
        deleted_users, deleted_artifacts = prune_inactive_users(days)
        click.echo(f"Deleted users: {deleted_users}, artifacts: {deleted_artifacts}")

    @app.cli.command('retention:prune-teams')
    @click.option('--days', default=365, type=int, help='Delete teams inactive for this many days')
    def retention_prune_teams(days):
        from coach.services.retention import prune_inactive_teams
        deleted_teams, deleted_files = prune_inactive_teams(days)
        click.echo(f"Deleted teams: {deleted_teams}, files: {deleted_files}")

    @app.errorhandler(Exception)
    def _log_unhandled_exception(exc):
        from flask import render_template
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            if getattr(exc, 'code', None) == 429:
                try:
                    from coach.auth_utils import get_team_id, get_team_role
                    from coach.services.logging import log_event
                    log_event('app.rate_limit', team_id=get_team_id(), role=get_team_role(), level='warning', message=str(exc))
                except Exception:
                    pass
            return exc
        # Full traceback to the server (PythonAnywhere) error log. The catch-all
        # handler below returns a 500 page, so Flask treats the error as handled
        # and skips its own traceback logging — without this line production
        # exceptions leave only a short audit row and are hard to diagnose. This
        # is the ONLY traceback logger, so no duplicate stack traces are emitted.
        try:
            from flask import request as _rq
            app.logger.exception('Unhandled exception on %s %s',
                                 getattr(_rq, 'method', '?'), getattr(_rq, 'path', '?'))
        except Exception:
            pass
        try:
            from coach.auth_utils import get_team_id, get_team_role
            from coach.services.logging import log_event
            log_event('app.exception', team_id=get_team_id(), role=get_team_role(), level='error', message=str(exc), meta={'type': exc.__class__.__name__})
        except Exception:
            pass
        try:
            return render_template('500.html'), 500
        except Exception:
            return ('Internal Server Error', 500)

    @app.errorhandler(429)
    def _rate_limited(exc):
        from flask import render_template, make_response
        try:
            from coach.auth_utils import get_team_id, get_team_role
            from coach.services.logging import log_event
            log_event('app.rate_limit', team_id=get_team_id(), role=get_team_role(), level='warning', message=str(exc))
        except Exception:
            pass
        # Preserve the HTTP 429 status and derive Retry-After from Flask-Limiter's
        # current breached limit (without enabling the X-RateLimit-* headers, which
        # would leak the configuration). Render a CoachHub-styled page.
        retry_after = None
        try:
            import time as _time
            from coach.extensions import limiter as _lim
            _cl = getattr(_lim, 'current_limit', None)
            if _cl is not None and getattr(_cl, 'reset_at', None):
                retry_after = max(1, int(_cl.reset_at - _time.time()))
        except Exception:
            pass
        try:
            resp = make_response(render_template('429.html', retry_after=retry_after), 429)
        except Exception:
            return exc  # never let the error page itself 500
        if retry_after:
            resp.headers['Retry-After'] = str(retry_after)
        return resp

    @app.before_request
    def _ensure_dev_database_ready():
        from coach.services.db_state import create_missing_dev_tables
        create_missing_dev_tables(app)

    @app.before_request
    def _ensure_owner_admin_bootstrap():
        from coach.services.owner_admin import ensure_owner_secret
        ensure_owner_secret(app)

    from coach.extensions import limiter as _limiter
    @app.route('/sw.js')
    @_limiter.exempt
    def service_worker():
        """Serve the service worker from the site root so its scope is '/'
        (a /static/ SW could only control /static/). Public, no auth gate.
        Exempt from rate limits: PWAs fetch/revalidate /sw.js automatically
        (e.g. on every foreground), which is not an abuse vector."""
        from flask import send_from_directory
        resp = send_from_directory(app.static_folder, 'sw.js', mimetype='application/javascript')
        resp.headers['Service-Worker-Allowed'] = '/'
        resp.headers['Cache-Control'] = 'no-cache'
        return resp

    return app

# --- Konfigurace z .env ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# .env je v kořeni repa (o úroveň výš než složka coach)
ENV_PATH = os.path.join(os.path.dirname(BASE_DIR), ".env")
load_dotenv(ENV_PATH)

# Secret + DB URL z .env (s robustním řešením cesty pro SQLite)
DEV_DEFAULT_SECRET_KEY = 'dev-secret-change-me'
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', DEV_DEFAULT_SECRET_KEY)
app.config['ADMIN_SECRET_KEY'] = os.getenv('ADMIN_SECRET_KEY')
app.config['OWNER_ACCESS_KEY'] = os.getenv('OWNER_ACCESS_KEY')
db_url = os.getenv('DB_URL') or os.getenv('DATABASE_URL')

def _resolve_sqlite_url(url: str) -> str:
    if not url or not url.startswith('sqlite:///'):
        return url
    # extrahuj cestu za sqlite:///
    rel = url[len('sqlite:///'):]
    # pokud není absolutní, převeď na absolutní vůči kořeni repa
    if not rel.startswith('/'):
        project_root = os.path.dirname(BASE_DIR)  # nad složkou coach
        abs_path = os.path.abspath(os.path.join(project_root, rel))
        # zajisti existenci složky
        try:
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        except Exception as e:
            app.logger.warning('Create SQLite dir failed (relative): %s', e)
        return 'sqlite:///' + abs_path
    # u absolutní cesty jen zajisti existenci složky
    try:
        os.makedirs(os.path.dirname(rel), exist_ok=True)
    except Exception as e:
        app.logger.warning('Create SQLite dir failed (absolute): %s', e)
    return url

if db_url:
    db_url = _resolve_sqlite_url(db_url)
else:
    # Fallback na původní sqlite soubor v coach/
    db_path = os.path.join(BASE_DIR, 'players.db')
    db_url = f"sqlite:///{db_path}"
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# --- Engine options: safe under concurrency, portable to future backends ---
# pool_pre_ping avoids handing out a pooled connection that went stale while the
# PythonAnywhere worker idled. For SQLite we also raise the busy timeout so
# concurrent writers WAIT (up to 30 s) for the write lock instead of failing
# immediately with "database is locked" — the main cause of save errors under
# concurrency. WAL is intentionally NOT enabled (unsafe assumption on
# PythonAnywhere storage). connect_args apply ONLY to sqlite, so a future
# Postgres/MySQL DB_URL is unaffected.
_engine_options = {'pool_pre_ping': True}
if db_url.startswith('sqlite'):
    _engine_options['connect_args'] = {'timeout': 30}
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = _engine_options
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
# Protected export directory (not served by /static)
app.config['EXPORT_FOLDER'] = os.path.join(BASE_DIR, 'protected_exports')
os.makedirs(app.config['EXPORT_FOLDER'], exist_ok=True)
# Secure cookies (critical)
# Prepare environment flags
APP_ENV = (os.getenv('APP_ENV') or os.getenv('FLASK_ENV') or '').lower()
IS_DEV = APP_ENV in ('dev', 'development', 'local') or os.getenv('DEBUG') == '1' or bool(getattr(app, 'debug', False))
app.config['IS_DEV'] = IS_DEV

# --- Production secret hardening: fail fast at boot; never log secret values ---
# Signed session cookies protect owner_admin / team_id / team_role, so a missing
# or default SECRET_KEY in production would allow cookie forgery (full auth
# bypass). In development the dev default is still allowed for convenience.
if not IS_DEV:
    _raw_secret = os.getenv('SECRET_KEY')
    if not _raw_secret or _raw_secret == DEV_DEFAULT_SECRET_KEY:
        raise RuntimeError(
            'SECRET_KEY is missing or set to the insecure development default. '
            'Set a strong, unique SECRET_KEY environment variable before running '
            'in production (APP_ENV is not development).'
        )
    if not (os.getenv('ADMIN_SECRET_KEY') or '').strip():
        raise RuntimeError(
            'ADMIN_SECRET_KEY is required in production to enable owner admin '
            'access. OWNER_ACCESS_KEY is not accepted as the production owner key. '
            'Set the ADMIN_SECRET_KEY environment variable.'
        )

# In dev, re-read templates on every request so edits take effect WITHOUT a server
# restart. Without this, Jinja caches compiled templates in memory and a long-running
# `flask run` process keeps serving the stale page (e.g. a calendar template missing
# its newer inline JS), which silently breaks client-side enhancements.
if IS_DEV:
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.jinja_env.auto_reload = True
    app.jinja_env.cache = {}

from coach.services.owner_admin import ensure_owner_secret
ensure_owner_secret(app)

# Secure cookies – relax in dev (HTTP)
app.config['SESSION_COOKIE_SECURE'] = not IS_DEV
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['REMEMBER_COOKIE_SECURE'] = not IS_DEV
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'
# Global request size limit (2 MB)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024
# Email config removed (team-only mode)
app.config['EMAIL_TOKEN_MAX_AGE'] = int(os.getenv('EMAIL_TOKEN_MAX_AGE', '172800'))
app.config['PASSWORD_RESET_TOKEN_MAX_AGE'] = int(os.getenv('PASSWORD_RESET_TOKEN_MAX_AGE', '3600'))
# Terms & Privacy
app.config['TERMS_VERSION'] = os.getenv('TERMS_VERSION', 'v1.0')
# Persistent session lifetime (for team sessions)
try:
    _sess_days = int(os.getenv('SESSION_LIFETIME_DAYS', '30'))
except Exception:
    _sess_days = 30
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=max(1, min(_sess_days, 365)))
# Enforce email confirmation (production default: on). Set REQUIRE_EMAIL_CONFIRMATION=0 to relax.
def _env_bool(key: str, default: bool = True) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return str(v).strip().lower() in ('1', 'true', 'yes', 'y', 'on')
app.config['REQUIRE_EMAIL_CONFIRMATION'] = _env_bool('REQUIRE_EMAIL_CONFIRMATION', True)

# Lazy extensions
from coach.extensions import db, migrate, login_manager, bcrypt, csrf, limiter
db.init_app(app)
migrate.init_app(app, db)
login_manager.init_app(app)
login_manager.login_view = 'team_auth'
login_manager.login_message = None  # Disable default Flask-Login flash
bcrypt.init_app(app)
csrf.init_app(app)
limiter.init_app(app)

# Minimal Flask-Login loaders to satisfy template context (team-only mode)
@login_manager.user_loader
def _noop_user_loader(user_id: str):
    return None

@login_manager.request_loader
def _noop_request_loader(req):
    return None

# Build app via factory to finish setup
app = create_app()

# Trust exactly ONE proxy hop (PythonAnywhere's front-end). This makes
# `request.remote_addr` the REAL client IP (the right-most, proxy-appended
# X-Forwarded-For value) so the rate limiter buckets each client separately
# instead of lumping everyone under the shared proxy IP. x_for=1 takes only the
# hop the trusted proxy added, so a client cannot spoof its IP by prepending
# X-Forwarded-For values. x_proto/x_host also fix https/host for external URLs.
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# --- Logo upload constraints ---
ALLOWED_LOGO_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2 MB

def allowed_logo_file(filename: str) -> bool:
    return bool(filename) and '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_LOGO_EXTENSIONS

def _save_logo_file(logo_f) -> tuple[str | None, str | None]:
    """Validate, resize and save logo image with dedup.
    Returns (error_message, relative_path) where relative_path is under
    static as 'uploads/<filename>'. If an identical image was already saved,
    it reuses the existing file path instead of creating a duplicate.
    """
    try:
        fname = getattr(logo_f, 'filename', '') or ''
        if not fname or not allowed_logo_file(fname):
            return ("Nepovolený typ souboru loga.", None)
        # size check
        fobj = getattr(logo_f, 'stream', logo_f)
        try:
            fobj.seek(0, os.SEEK_END)
            size = fobj.tell()
            fobj.seek(0)
        except Exception as e:
            app.logger.warning('Logo size check failed: %s', e)
            size = 0
        if size and size > MAX_LOGO_SIZE:
            return ("Logo je příliš velké (max 2 MB).", None)
        # open and thumbnail
        im = Image.open(fobj)
        # convert and resize; keep alpha if present (better for logos)
        try:
            im = im.convert("RGBA")
        except Exception as e:
            app.logger.warning('Logo RGBA convert failed, fallback: %s', e)
            im = im.convert("RGB")
        # auto-trim transparent borders if any (nice cropping for logos)
        try:
            if 'A' in im.getbands():
                alpha = im.split()[3]
                bbox = alpha.getbbox()
                if bbox:
                    im = im.crop(bbox)
        except Exception as e:
            app.logger.warning('Logo autocrop failed: %s', e)
        # scale to fit within 512x512 preserving aspect ratio
        im.thumbnail((512, 512))
        # serialize to PNG in-memory for hashing (normalized content)
        buf = io.BytesIO()
        im.save(buf, format='PNG', optimize=True)
        png_bytes = buf.getvalue()
        # compute content hash to deduplicate identical images
        h = hashlib.sha256(png_bytes).hexdigest()
        safe = secure_filename(fname) or 'logo'
        stem, _ext = os.path.splitext(safe)
        out_name = f"{stem}-{h[:16]}.png"
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], out_name)
        # if an identical image already exists, reuse it; otherwise write
        if not os.path.exists(save_path):
            with open(save_path, 'wb') as f:
                f.write(png_bytes)
        return (None, f"uploads/{out_name}")
    except Exception as e:
        app.logger.warning('Logo processing error: %s', e)
        return ("Nepodařilo se zpracovat logo.", None)


# --- Role helpers ---
from coach.auth_utils import coach_required as _coach_required, team_login_required as _team_login_required, get_team_id as _get_team_id, get_team_role as _get_team_role


def coach_required(fn):
    return _coach_required(fn)


def team_login_required(fn):
    return _team_login_required(fn)


def get_team_id() -> int | None:
    return _get_team_id()


def get_team_role() -> str:
    return _get_team_role()


# --- Spuštění ---
if __name__ == "__main__":
    with app.app_context():
        # In dev, auto-create tables for quick start. In production, use Alembic.
        if app.config.get('IS_DEV'):
            db.create_all()
    app.run(debug=bool(app.config.get('IS_DEV')))
