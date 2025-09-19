from flask import Flask, request, redirect, url_for, flash
import os
import io
from datetime import datetime, timedelta
from PIL import Image
import hashlib
from dotenv import load_dotenv
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from functools import wraps
 

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
    _reg('coach.blueprints.settings', 'settings')

    # Provide top-level endpoint aliases
    try:
        aliases = [
            ('/team/auth', 'team_auth', 'teamauth.team_auth', None),
            ('/team/login', 'team_login', 'teamauth.team_login', ['POST']),
            ('/team/logout', 'team_logout', 'teamauth.team_logout', None),
            ('/team/create', 'team_create', 'teamauth.team_create', ['POST']),
            ('/team/keys', 'team_keys', 'teamauth.team_keys', ['GET','POST']),
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

    return app

# --- Konfigurace z .env ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# .env je v kořeni repa (o úroveň výš než složka coach)
ENV_PATH = os.path.join(os.path.dirname(BASE_DIR), ".env")
load_dotenv(ENV_PATH)

# Secret + DB URL z .env (s robustním řešením cesty pro SQLite)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-change-me')
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

from coach.models import Team

# Minimal Flask-Login loaders to satisfy template context (team-only mode)
@login_manager.user_loader
def _noop_user_loader(user_id: str):
    return None

@login_manager.request_loader
def _noop_request_loader(req):
    return None

# Build app via factory to finish setup
app = create_app()

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
def coach_required(fn):
    @wraps(fn)
    def _wrap(*args, **kwargs):
        from flask import session
        # Accept either Flask-Login coach or team-session coach
        if current_user.is_authenticated:
            if getattr(current_user, 'role', 'player') != 'coach':
                flash('Tuto akci může provést pouze trenér.', 'error')
                return redirect(request.referrer or url_for('home'))
        else:
            if not (session.get('team_login') and session.get('team_role') == 'coach'):
                return redirect(url_for('team_auth'))
        return fn(*args, **kwargs)
    return _wrap

# New: team login required (session-based)
def team_login_required(fn):
    @wraps(fn)
    def _wrap(*args, **kwargs):
        from flask import session
        if session.get('team_login') and session.get('team_id'):
            return fn(*args, **kwargs)
        # fallback: accept legacy user login
        if getattr(current_user, 'is_authenticated', False):
            return fn(*args, **kwargs)
        return redirect(url_for('team_auth'))
    return _wrap

def get_team_id() -> int | None:
    from flask import session
    tid = session.get('team_id')
    if tid:
        return int(tid)
    try:
        if current_user.is_authenticated and getattr(current_user, 'team_id', None):
            return int(current_user.team_id)
    except Exception:
        pass
    return None

def get_team_role() -> str:
    from flask import session
    r = session.get('team_role')
    if r:
        return r
    try:
        if current_user.is_authenticated:
            return getattr(current_user, 'role', 'player') or 'player'
    except Exception:
        pass
    return 'player'


# --- Spuštění ---
if __name__ == "__main__":
    with app.app_context():
        # In dev, auto-create tables for quick start. In production, use Alembic.
        if app.config.get('IS_DEV'):
            db.create_all()
    app.run(debug=bool(app.config.get('IS_DEV')))
