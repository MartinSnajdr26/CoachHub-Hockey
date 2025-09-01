from flask import Flask, render_template, request, redirect, url_for, send_file, flash
from flask_sqlalchemy import SQLAlchemy
import os
import io
import uuid
import base64
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
from flask_migrate import Migrate
from flask_login import (
    LoginManager, login_user, logout_user, login_required,
    current_user, UserMixin
)
from flask_bcrypt import Bcrypt
from werkzeug.utils import secure_filename
from functools import wraps
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf import CSRFProtect
import calendar
from datetime import date

app = Flask(__name__)

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

# Secure cookies – relax in dev (HTTP)
app.config['SESSION_COOKIE_SECURE'] = not IS_DEV
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['REMEMBER_COOKIE_SECURE'] = not IS_DEV
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'
# Global request size limit (2 MB)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024
# SMTP config
app.config['SMTP_SERVER'] = os.getenv('SMTP_SERVER')
app.config['SMTP_PORT'] = int(os.getenv('SMTP_PORT', '587'))
app.config['SMTP_USER'] = os.getenv('SMTP_USER')
app.config['SMTP_PASSWORD'] = os.getenv('SMTP_PASSWORD')
app.config['MAIL_SENDER'] = os.getenv('MAIL_SENDER', 'martinsnajdr@coachhubhockey.com')
app.config['EMAIL_TOKEN_MAX_AGE'] = int(os.getenv('EMAIL_TOKEN_MAX_AGE', '172800'))
app.config['PASSWORD_RESET_TOKEN_MAX_AGE'] = int(os.getenv('PASSWORD_RESET_TOKEN_MAX_AGE', '3600'))

db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'auth'
# Disable default Flask-Login flash message shown on redirect to login
login_manager.login_message = None
bcrypt = Bcrypt(app)
csrf = CSRFProtect(app)
limiter = Limiter(get_remote_address, app=app, default_limits=["200 per day", "50 per hour"])

def make_serializer():
    return URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='email-verify')

def make_reset_serializer():
    return URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='password-reset')

from flask import g
import secrets

@app.before_request
def _set_csp_nonce():
    g.csp_nonce = secrets.token_urlsafe(16)

@app.context_processor
def _inject_csp_nonce():
    return {'csp_nonce': getattr(g, 'csp_nonce', '')}

@app.after_request
def set_security_headers(resp):
    # HSTS (only meaningful over HTTPS)
    if not IS_DEV:
        resp.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains; preload')
    else:
        resp.headers.setdefault('Strict-Transport-Security', 'max-age=0')
    # Basic hardening
    resp.headers.setdefault('X-Frame-Options', 'DENY')
    resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
    resp.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    resp.headers.setdefault('Permissions-Policy', "geolocation=(), microphone=(), camera=(), payment=()")
    # CSP – nonce-based, allow inline only in dev to avoid breakage until all templates are refactored
    script_src = ["'self'", f"'nonce-{getattr(g, 'csp_nonce', '')}'"]
    if IS_DEV:
        script_src.append("'unsafe-inline'")
    csp = (
        "default-src 'self'; "
        "img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        f"script-src {' '.join(script_src)}"
    )
    resp.headers.setdefault('Content-Security-Policy', csp)
    return resp

# --- Logo upload constraints ---
ALLOWED_LOGO_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2 MB

def allowed_logo_file(filename: str) -> bool:
    return bool(filename) and '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_LOGO_EXTENSIONS

def _save_logo_file(logo_f) -> tuple[str | None, str | None]:
    """Validate, resize and save logo image. Returns (error_message, relative_path).
    relative_path is under static as 'uploads/<filename>'.
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
        # convert and resize; always output PNG and strip EXIF
        try:
            im = im.convert("RGB")
        except Exception as e:
            app.logger.warning('Logo RGB convert failed, fallback: %s', e)
            im = im.convert("RGB")
        im.thumbnail((512, 512))
        # build safe unique filename with .png extension
        safe = secure_filename(fname)
        stem, _ext = os.path.splitext(safe)
        token = uuid.uuid4().hex[:8]
        out_name = f"{stem}-{token}.png"
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], out_name)
        # always save as PNG
        im.save(save_path, format='PNG', optimize=True)
        return (None, f"uploads/{out_name}")
    except Exception as e:
        app.logger.warning('Logo processing error: %s', e)
        return ("Nepodařilo se zpracovat logo.", None)

# --- Model hráče ---
class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    position = db.Column(db.String(10), nullable=False)  # F, D, G

    def __repr__(self):
        return f"<Player {self.name} ({self.position})>"

# --- Model nominace na zápas ---
class Roster(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    player_id = db.Column(db.Integer, db.ForeignKey("player.id"))
    player = db.relationship("Player")

class LineAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    player_id = db.Column(db.Integer, db.ForeignKey("player.id"))
    slot = db.Column(db.String(10))  # např. L1F1, L1F2, D1-1, G1...
    player = db.relationship("Player")

class Drill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    duration = db.Column(db.Integer, nullable=True)  # v minutách
    category = db.Column(db.String(50), nullable=True)
    image_data = db.Column(db.Text, nullable=True)   # obrázek uložený jako base64
    path_data = db.Column(db.Text, nullable=True)    # JSON s daty animace

class TrainingSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(300), nullable=False)  # název PDF souboru (uložen v EXPORT_FOLDER)
    drill_ids = db.Column(db.Text, nullable=True)         # CSV nebo JSON se seznamem ID
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class LineupSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)  # Sestava - Zápas - "Soupeř" - datum
    filename = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# --- Multi-team: Team a User ---
class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    primary_color = db.Column(db.String(20), nullable=True)
    secondary_color = db.Column(db.String(20), nullable=True)
    logo_path = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    users = db.relationship('User', backref='team', lazy=True)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    action = db.Column(db.String(50), nullable=False)
    details = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    username = db.Column(db.String(100), unique=True, nullable=True)
    first_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.String(100), nullable=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='coach')  # 'coach' | 'player'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_team_admin = db.Column(db.Boolean, default=False)
    is_approved = db.Column(db.Boolean, default=True)
    email_confirmed = db.Column(db.Boolean, default=False)
    email_confirmed_at = db.Column(db.DateTime, nullable=True)

    def set_password(self, password: str):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password: str) -> bool:
        try:
            return bcrypt.check_password_hash(self.password_hash, password)
        except Exception:
            return False




class TrainingEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    day = db.Column(db.Date, nullable=False)
    time = db.Column(db.String(10), nullable=True)  # HH:MM
    title = db.Column(db.String(200), nullable=False, default='Trénink')
    kind = db.Column(db.String(20), nullable=True)  # 'training' | 'match'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id: str):
    try:
        return User.query.get(int(user_id))
    except Exception:
        return None


# --- Auth routes (minimal) ---
@app.route('/auth')
def auth():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    teams = Team.query.order_by(Team.name.asc()).all()
    return render_template('auth.html', teams=teams)

@app.route('/register', methods=['POST'])
def register():
    print("➡️ /register spuštěno")
    email = (request.form.get('email') or '').strip().lower()
    print("📧 Email z formuláře:", email)
    password = request.form.get('password') or ''
    print("🔑 Password len:", len(password))
    first_name = (request.form.get('first_name') or '').strip()
    last_name = (request.form.get('last_name') or '').strip()
    team_name = (request.form.get('team_name') or '').strip()
    role = (request.form.get('role') or 'coach').strip()
    primary = (request.form.get('primary_color') or '').strip()
    secondary = (request.form.get('secondary_color') or '').strip()
    logo_f = request.files.get('team_logo')
    team_mode = (request.form.get('team_mode') or 'create').strip()  # 'create' | 'join'
    existing_team_id = request.form.get('existing_team')
    if not email or not password:
        print("❌ Registrace selhala: email nebo heslo prázdné")
        return redirect(url_for('home'))
    if User.query.filter_by(email=email).first():
        print("❌ Registrace selhala: email už existuje v DB")
        return redirect(url_for('home'))
    team = None
    if team_mode == 'join' and existing_team_id:
        try:
            team = Team.query.get(int(existing_team_id))
        except Exception:
            team = None
    elif team_name:
        # pokud tým se stejným názvem existuje, připoj se, jinak vytvoř
        existing = Team.query.filter_by(name=team_name).first()
        if existing:
            team = existing
        else:
            team = Team(name=team_name)
            if primary:
                team.primary_color = primary
            if secondary:
                team.secondary_color = secondary
            if logo_f and getattr(logo_f, 'filename', ''):
                err, rel = _save_logo_file(logo_f)
                if err:
                    # při registraci jen upozorni a pokračuj bez loga
                    try:
                        flash(err, 'error')
                    except Exception:
                        pass
                elif rel:
                    team.logo_path = rel
            db.session.add(team)
            db.session.flush()
    user = User(email=email, role=role, first_name=first_name or None, last_name=last_name or None)
    if team:
        user.team_id = team.id
    # approval + admin flags
    if team and team_mode == 'join':
        user.is_approved = False
        user.is_team_admin = False
    else:
        # zakladatel nového týmu je admin a schválen
        user.is_approved = True
        user.is_team_admin = True if team else False
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    print("✅ User uložen do DB:", user.email)

    # send verification email
    try:
        print("📨 Zkouším poslat e-mail...")
        send_verification_email(user)
        print("✅ send_verification_email proběhlo")
    except Exception as e:
        print("❌ Email error:", e)

    login_user(user)
    print("👤 Uživatel přihlášen:", user.email)

    # pokud čeká na schválení, pošli na čekací obrazovku
    if not user.is_approved:
        print("⏳ Uživateli chybí approval, redirect na /awaiting")
        return redirect(url_for('awaiting'))
    print("➡️ Redirect na /home")
    return redirect(url_for('home'))



@app.route('/login', methods=['POST'])
@limiter.limit('5 per minute')
def login():
    email = (request.form.get('email') or '').strip().lower()
    password = request.form.get('password') or ''
    user = User.query.filter_by(email=email).first()
    if user:
        ok = False
        # robustní ověření hesla i při starých objektech
        if hasattr(user, 'check_password'):
            try:
                ok = user.check_password(password)
            except Exception:
                ok = False
        if not ok:
            try:
                ok = bcrypt.check_password_hash(user.password_hash, password)
            except Exception:
                ok = False
        if ok:
            login_user(user)
            return redirect(url_for('home'))
    return redirect(url_for('home'))


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

# --- Gate nepovoleným uživatelům bez schválení ---
@app.before_request
def require_approval():
    from flask import request
    if not current_user.is_authenticated:
        return
    if getattr(current_user, 'email_confirmed', False) and getattr(current_user, 'is_approved', True):
        return
    allowed = {
        'awaiting', 'logout', 'auth', 'login', 'register', 'static', 'verify_email'
    }
    ep = request.endpoint or ''
    if ep.split('.')[0] not in allowed:
        return redirect(url_for('awaiting'))

@app.route('/awaiting')
def awaiting():
    # Pusť domů jen pokud je splněno potvrzení e‑mailu i schválení týmem
    if current_user.is_authenticated and getattr(current_user, 'email_confirmed', False) and getattr(current_user, 'is_approved', True):
        return redirect(url_for('home'))
    return render_template('awaiting.html')


def ensure_team_admins():
    """Idempotent fix: zajistí, aby každý tým měl alespoň jednoho admina.
    Vybere nejstaršího člena týmu a nastaví mu admin + approved, pokud tým nemá admina.
    """
    try:
        teams = Team.query.all()
        changed = False
        for t in teams:
            if not t:
                continue
            admin_count = User.query.filter_by(team_id=t.id, is_team_admin=True).count()
            if admin_count == 0:
                candidate = User.query.filter_by(team_id=t.id).order_by(User.created_at.asc()).first()
                if candidate:
                    candidate.is_team_admin = True
                    candidate.is_approved = True
                    if not getattr(candidate, 'email_confirmed', False):
                        candidate.email_confirmed = True
                        candidate.email_confirmed_at = datetime.utcnow()
                    changed = True
            # backfill: všem existujícím adminům bez potvrzení e‑mailu ho zapni (legacy účty)
            admins = User.query.filter_by(team_id=t.id, is_team_admin=True).all()
            for u in admins:
                if not getattr(u, 'email_confirmed', False):
                    u.email_confirmed = True
                    u.email_confirmed_at = datetime.utcnow()
                    changed = True
        if changed:
            db.session.commit()
    except Exception as e:
        app.logger.warning('ensure_team_admins failed: %s', e)
        db.session.rollback()


# Fallback: spusť jednou při prvním requestu (funguje i s app.run i flask run)
_ADMIN_FIX_RAN = False

@app.before_request
def _run_ensure_team_admins_once():
    global _ADMIN_FIX_RAN
    if _ADMIN_FIX_RAN:
        return
    ensure_team_admins()
    _ADMIN_FIX_RAN = True


# --- Brand context (logo + barvy týmu) ---
@app.context_processor
def inject_brand():
    brand = {'logo_url': None, 'primary': None, 'secondary': None, 'team_name': None}
    try:
        if current_user.is_authenticated and current_user.team_id:
            t = Team.query.get(current_user.team_id)
            if t:
                if t.logo_path:
                    brand['logo_url'] = url_for('static', filename=t.logo_path)
                brand['primary'] = t.primary_color or None
                brand['secondary'] = t.secondary_color or None
                brand['team_name'] = t.name or None
    except Exception as e:
        app.logger.warning('inject_brand failed: %s', e)
    return dict(brand=brand)


# --- Role helpers ---
def coach_required(fn):
    @wraps(fn)
    def _wrap(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth'))
        if getattr(current_user, 'role', 'player') != 'coach':
            flash('Tuto akci může provést pouze trenér.', 'error')
            return redirect(request.referrer or url_for('home'))
        return fn(*args, **kwargs)
    return _wrap


from email.mime.text import MIMEText
import smtplib


def send_verification_email(user: 'User'):
    try:
        token = make_serializer().dumps({'uid': user.id, 'email': user.email})
        verify_url = url_for('verify_email', token=token, _external=True)
        subject = 'Potvrzení registrace – CoachHub Hockey'
        body = f"Ahoj,\n\npro potvrzení registrace klikni na odkaz:\n{verify_url}\n\nOdkaz je platný {app.config['EMAIL_TOKEN_MAX_AGE']//3600} hodin.\n\nCoachHub Hockey"
        server = app.config.get('SMTP_SERVER')
        if not server:
            print("❌ SMTP_SERVER není nastavený")
            return
        msg = MIMEText(body, _charset='utf-8')
        msg['Subject'] = subject
        msg['From'] = app.config['MAIL_SENDER']
        msg['To'] = user.email
        port = app.config.get('SMTP_PORT', 587)
        usern = app.config.get('SMTP_USER')
        pwd = app.config.get('SMTP_PASSWORD')

        app.logger.info("Sending verify email via %s:%s as %s", server, port, usern)
        with smtplib.SMTP(server, port) as s:
            s.starttls()
            if usern and pwd:
                s.login(usern, pwd)
            s.send_message(msg)
        app.logger.info("Verification mail sent to %s", user.email)

    except Exception as e:
        app.logger.warning("Sending verification email failed: %s", e)


def send_password_reset_email(user: 'User'):
    try:
        token = make_reset_serializer().dumps({'uid': user.id, 'email': user.email})
        reset_url = url_for('password_reset', token=token, _external=True)
        # Brand/team context
        team_name = None
        try:
            if user.team_id:
                t = Team.query.get(user.team_id)
                if t and t.name:
                    team_name = t.name
        except Exception:
            team_name = None
        subject_brand = f" – {team_name}" if team_name else ""
        subject = f'Obnova hesla{subject_brand} – CoachHub Hockey'
        body = (
            "Ahoj,\n\n" 
            + (f"tým: {team_name}\n\n" if team_name else "")
            + "požádal(a) jsi o obnovení hesla. Klikni na odkaz a nastav nové heslo:\n"
            f"{reset_url}\n\n"
            f"Odkaz je platný {app.config['PASSWORD_RESET_TOKEN_MAX_AGE']//60} minut.\n\n"
            "Pokud jsi to nebyl(a) ty, tento e-mail ignoruj.\n\n"
            "CoachHub Hockey"
        )
        server = app.config.get('SMTP_SERVER')
        if not server:
            print("❌ SMTP_SERVER není nastavený")
            return
        msg = MIMEText(body, _charset='utf-8')
        msg['Subject'] = subject
        msg['From'] = app.config['MAIL_SENDER']
        msg['To'] = user.email
        port = app.config.get('SMTP_PORT', 587)
        usern = app.config.get('SMTP_USER')
        pwd = app.config.get('SMTP_PASSWORD')

        with smtplib.SMTP(server, port) as s:
            s.starttls()
            if usern and pwd:
                s.login(usern, pwd)
            s.send_message(msg)
        print(f"✅ Reset e-mail odeslán na {user.email}")
    except Exception as e:
        print("❌ Chyba při posílání reset e-mailu:", e)



@app.route('/verify/<token>')
def verify_email(token):
    s = make_serializer()
    try:
        data = s.loads(token, max_age=app.config['EMAIL_TOKEN_MAX_AGE'])
        uid = int(data.get('uid'))
        email = data.get('email')
    except (SignatureExpired, BadSignature, Exception):
        flash('Odkaz pro potvrzení vypršel nebo je neplatný.', 'error')
        return redirect(url_for('auth'))
    user = User.query.get(uid)
    if not user or user.email != email:
        flash('Odkaz pro potvrzení je neplatný.', 'error')
        return redirect(url_for('auth'))
    if not user.email_confirmed:
        user.email_confirmed = True
        user.email_confirmed_at = datetime.utcnow()
        db.session.commit()
    flash('E-mail byl úspěšně potvrzen.', 'success')
    if not current_user.is_authenticated:
        login_user(user)
    if not user.is_approved:
        return redirect(url_for('awaiting'))
    return redirect(url_for('home'))


# --- Password reset ---
@app.route('/password/forgot', methods=['GET', 'POST'])
@limiter.limit('5 per hour')
def password_forgot():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        # Always show generic response to avoid user enumeration
        try:
            user = User.query.filter_by(email=email).first()
            if user:
                send_password_reset_email(user)
                try:
                    db.session.add(AuditLog(team_id=user.team_id, actor_user_id=user.id, target_user_id=user.id, action='password_reset_requested'))
                    db.session.commit()
                except Exception as e:
                    app.logger.warning('Audit log write failed (reset requested): %s', e)
        except Exception as e:
            app.logger.warning('Password reset request handling failed: %s', e)
        flash('Pokud účet existuje, poslali jsme odkaz na reset hesla.', 'info')
        return redirect(url_for('auth'))
    return render_template('password_request.html')


@app.route('/password/reset/<token>', methods=['GET', 'POST'])
@limiter.limit('10 per hour')
def password_reset(token):
    s = make_reset_serializer()
    try:
        data = s.loads(token, max_age=app.config['PASSWORD_RESET_TOKEN_MAX_AGE'])
        uid = int(data.get('uid'))
        email = data.get('email')
    except (SignatureExpired, BadSignature, Exception) as e:
        app.logger.warning('Password reset token invalid/expired: %s', e)
        flash('Odkaz pro reset hesla je neplatný nebo vypršel.', 'error')
        return redirect(url_for('auth'))
    user = User.query.get(uid)
    if not user or user.email != email:
        flash('Odkaz pro reset hesla je neplatný.', 'error')
        return redirect(url_for('auth'))
    if request.method == 'POST':
        pw1 = request.form.get('password') or ''
        pw2 = request.form.get('password_confirm') or ''
        if len(pw1) < 8:
            flash('Heslo musí mít alespoň 8 znaků.', 'error')
            return render_template('password_reset.html', token=token)
        if pw1 != pw2:
            flash('Hesla se neshodují.', 'error')
            return render_template('password_reset.html', token=token)
        try:
            user.set_password(pw1)
            try:
                db.session.add(AuditLog(team_id=user.team_id, actor_user_id=user.id, target_user_id=user.id, action='password_reset', details='Password reset via email token'))
            except Exception:
                pass
            db.session.commit()
            flash('Heslo bylo změněno. Můžeš se přihlásit.', 'success')
        except Exception as e:
            db.session.rollback()
            app.logger.warning('Password reset failed: %s', e)
            flash('Nepodařilo se změnit heslo.', 'error')
            return render_template('password_reset.html', token=token)
        return redirect(url_for('auth'))
    return render_template('password_reset.html', token=token)


# --- Settings: change team logo and colors ---
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    # ensure user has a team
    team = None
    if current_user.team_id:
        team = Team.query.get(current_user.team_id)
    if request.method == 'POST':
        action = (request.form.get('action') or 'brand').strip()
        # --- Update brand (colors + logo)
        if action == 'brand':
            # Only team admins/coaches can change team brand
            if getattr(current_user, 'role', 'player') != 'coach' or not current_user.is_team_admin:
                flash('Pouze týmový admin může měnit nastavení týmu.', 'error')
                return redirect(url_for('settings'))
            primary = (request.form.get('primary_color') or '').strip()
            secondary = (request.form.get('secondary_color') or '').strip()
            logo_f = request.files.get('team_logo')
            if not team:
                # create a default team if missing
                name = request.form.get('team_name') or (current_user.username or 'Můj tým')
                team = Team(name=name)
                db.session.add(team)
                db.session.flush()
                current_user.team_id = team.id
            if primary:
                team.primary_color = primary
            if secondary:
                team.secondary_color = secondary
            if logo_f and getattr(logo_f, 'filename', ''):
                err, rel = _save_logo_file(logo_f)
                if err:
                    flash(err, 'error')
                    return redirect(url_for('settings'))
                if rel:
                    team.logo_path = rel
            db.session.commit()
            try:
                db.session.add(AuditLog(team_id=current_user.team_id, actor_user_id=current_user.id, action='team_brand_update', details='Updated team brand'))
                db.session.commit()
            except Exception:
                pass
            return redirect(url_for('settings'))
        # --- Update account (email/username/password)
        elif action == 'account':
            new_email = (request.form.get('email') or '').strip().lower()
            new_username = (request.form.get('username') or '').strip() or None
            current_pw = request.form.get('current_password') or ''
            new_pw = request.form.get('new_password') or ''
            # Email change
            if new_email and new_email != current_user.email:
                if not User.query.filter(User.id != current_user.id, User.email == new_email).first():
                    current_user.email = new_email
            # Username change
            if new_username != current_user.username:
                if new_username is None or not User.query.filter(User.id != current_user.id, User.username == new_username).first():
                    current_user.username = new_username
            # Password change (require current)
            if new_pw:
                if current_user.check_password(current_pw):
                    current_user.set_password(new_pw)
            db.session.commit()
            return redirect(url_for('settings'))
        # --- Delete account
        elif action == 'delete':
            uid = current_user.id
            logout_user()
            u = User.query.get(uid)
            if u:
                db.session.delete(u)
                db.session.commit()
            return redirect(url_for('auth'))
    # GET
    members = []
    if current_user.team_id:
        members = User.query.filter_by(team_id=current_user.team_id).order_by(User.created_at.asc()).all()
    return render_template('settings.html', team=team, members=members)


@app.route('/team/members/action', methods=['POST'])
@login_required
def team_members_action():
    if not current_user.team_id or not current_user.is_team_admin:
        return redirect(url_for('settings'))
    target_id = request.form.get('user_id')
    action = request.form.get('action')
    try:
        target = User.query.get(int(target_id))
    except Exception:
        target = None
    if not target or target.team_id != current_user.team_id:
        return redirect(url_for('settings'))
    if action == 'approve':
        target.is_approved = True
        try:
            db.session.add(AuditLog(team_id=current_user.team_id, actor_user_id=current_user.id, target_user_id=target.id, action='approve', details=f"Approved {target.email}"))
        except Exception:
            pass
    elif action == 'revoke':
        target.is_approved = False
        try:
            db.session.add(AuditLog(team_id=current_user.team_id, actor_user_id=current_user.id, target_user_id=target.id, action='revoke', details=f"Revoked {target.email}"))
        except Exception:
            pass
    elif action == 'set_role':
        value = (request.form.get('value') or 'player').strip()
        if value in ('coach','player'):
            target.role = value
            try:
                db.session.add(AuditLog(team_id=current_user.team_id, actor_user_id=current_user.id, target_user_id=target.id, action='set_role', details=f"Role -> {value}"))
            except Exception:
                pass
    elif action == 'make_admin':
        target.is_team_admin = True
        try:
            db.session.add(AuditLog(team_id=current_user.team_id, actor_user_id=current_user.id, target_user_id=target.id, action='make_admin'))
        except Exception:
            pass
    elif action == 'remove_admin':
        # nedovol odebrat si sám admina, pokud je jediný admin
        if target.id == current_user.id:
            others = User.query.filter_by(team_id=current_user.team_id, is_team_admin=True).filter(User.id != current_user.id).count()
            if others <= 0:
                return redirect(url_for('settings'))
        target.is_team_admin = False
        try:
            db.session.add(AuditLog(team_id=current_user.team_id, actor_user_id=current_user.id, target_user_id=target.id, action='remove_admin'))
        except Exception:
            pass
    elif action == 'remove_member':
        # zákaz odstranit sám sebe, použij smazání účtu
        if target.id != current_user.id:
            # pokud byl admin a je poslední, nedovol zrušit
            if target.is_team_admin:
                others = User.query.filter_by(team_id=current_user.team_id, is_team_admin=True).filter(User.id != target.id).count()
                if others <= 0:
                    return redirect(url_for('settings'))
            db.session.delete(target)
            try:
                db.session.add(AuditLog(team_id=current_user.team_id, actor_user_id=current_user.id, target_user_id=target.id, action='remove_member', details=f"Removed {target.email}"))
            except Exception:
                pass
            db.session.commit()
            return redirect(url_for('settings'))
    db.session.commit()
    return redirect(url_for('settings'))


# --- Kontext pro globální navigaci (kategorie tréninků) ---
@app.context_processor
def inject_drill_nav():
    try:
        q = db.session.query(Drill.category)
        if current_user.is_authenticated and current_user.team_id:
            q = q.filter(Drill.team_id == current_user.team_id)
        cats = q.distinct().all()
        categories = [c[0] for c in cats if c and c[0]]
    except Exception:
        categories = []
    return { 'nav_drill_categories': categories }


# --- Domovská stránka ---
@app.route("/")
@login_required
def home():
    # Month params
    try:
        y = int(request.args.get('year', ''))
        m = int(request.args.get('month', ''))
    except Exception:
        y = 0; m = 0
    from datetime import date
    today = date.today()
    if not (1 <= m <= 12) or y < 1900:
        y, m = today.year, today.month
    import calendar
    cal = calendar.Calendar(firstweekday=0)
    weeks = []
    for wk in cal.monthdatescalendar(y, m):
        weeks.append(list(wk))
    # Fetch events for this month
    first_day = date(y, m, 1)
    if m == 12:
        next_first = date(y+1, 1, 1)
    else:
        next_first = date(y, m+1, 1)
    from datetime import timedelta
    last_day = next_first - timedelta(days=1)
    events_by_day = {}
    if current_user.team_id:
        evs = TrainingEvent.query.filter(
            TrainingEvent.team_id == current_user.team_id,
            TrainingEvent.day >= first_day,
            TrainingEvent.day <= last_day
        ).order_by(TrainingEvent.day.asc(), TrainingEvent.time.asc()).all()
        for e in evs:
            key = e.day.isoformat()
            events_by_day.setdefault(key, []).append(e)
    # Prev/next
    if m == 1:
        prev_y, prev_m = y-1, 12
    else:
        prev_y, prev_m = y, m-1
    if m == 12:
        next_y, next_m = y+1, 1
    else:
        next_y, next_m = y, m+1
    cs_months = ['-', "leden","únor","březen","duben","květen","červen",
                 "červenec","srpen","září","říjen","listopad","prosinec"]
    month_title = f"{cs_months[m]} {y}"
    today_label = f"{today.day}. {cs_months[today.month]} {today.year}"
    return render_template(
        "home.html",
        cal_year=y, cal_month=m, month_title=month_title, weeks=weeks,
        events_by_day=events_by_day,
        prev_year=prev_y, prev_month=prev_m,
        next_year=next_y, next_month=next_m,
        today_label=today_label,
        today_iso=today.isoformat()
    )

# --- Seznam hráčů ---
@app.route("/players")
@login_required
def players():
    players = []
    if current_user.team_id:
        players = Player.query.filter_by(team_id=current_user.team_id).all()
    return render_template("players.html", players=players)

@app.route("/add_player", methods=["POST"])
@coach_required
def add_player():
    name = (request.form.get("name") or "").strip()
    position = request.form.get("position")
    if not (name and position in ["F", "D", "G"] and current_user.team_id):
        return redirect(url_for("players"))

    # kontrola duplicit ve stejném týmu
    existing = Player.query.filter_by(team_id=current_user.team_id, name=name).first()
    if existing:
        flash("Hráč s tímto jménem už v týmu existuje.", "error")
        return redirect(url_for("players"))

    new_player = Player(name=name, position=position, team_id=current_user.team_id)
    db.session.add(new_player)
    db.session.commit()
    flash("Hráč byl přidán.", "success")
    return redirect(url_for("players"))


@app.route("/delete_player/<int:player_id>", methods=["POST"])
@coach_required
def delete_player(player_id):
    player = Player.query.get(player_id)
    if player and player.team_id == current_user.team_id:
        db.session.delete(player)
        db.session.commit()
    return redirect(url_for("players"))

# --- Soupiska na zápas ---
@app.route("/roster", methods=["GET", "POST"])
@login_required
def roster():
    if request.method == "POST":
        if getattr(current_user, 'role', 'player') != 'coach':
            flash("Tuto akci může provést pouze trenér.", "error")
            return redirect(request.referrer or url_for("roster"))

        if not current_user.team_id:
            flash("Nemáš přiřazený tým.", "error")
            return redirect(url_for("roster"))

        # vymazat starou soupisku JEN pro tento tým
        Roster.query.filter_by(team_id=current_user.team_id).delete()
        db.session.commit()

        # uložit nové hráče
        selected_ids = request.form.getlist("players")
        for pid in selected_ids:
            roster_entry = Roster(player_id=int(pid), team_id=current_user.team_id)
            db.session.add(roster_entry)
        db.session.commit()

        return redirect(url_for("roster"))

    roster = []
    roster_ids = []
    players = []
    if current_user.team_id:
        players = Player.query.filter_by(team_id=current_user.team_id).all()
        roster = Roster.query.filter_by(team_id=current_user.team_id).all()
        roster_ids = [r.player_id for r in roster]

    return render_template("roster.html", players=players, roster=roster, roster_ids=roster_ids)


@app.route("/lines", methods=["GET", "POST"])
@login_required
def lines():
    if request.method == "POST":
        if getattr(current_user, 'role', 'player') != 'coach':
            flash("Tuto akci může provést pouze trenér.", "error")
            return redirect(request.referrer or url_for("lines"))

        if not current_user.team_id:
            flash("Nemáš přiřazený tým.", "error")
            return redirect(url_for("lines"))

        # smažeme staré rozdělení jen pro tento tým
        LineAssignment.query.filter_by(team_id=current_user.team_id).delete()
        db.session.commit()

        # uložíme nové přiřazení
        for slot, pid in request.form.items():
            if slot == 'csrf_token':
                continue
            if not pid:
                continue
            try:
                player_id = int(pid)
            except (TypeError, ValueError):
                continue

            assignment = LineAssignment(player_id=player_id, slot=slot, team_id=current_user.team_id)
            db.session.add(assignment)

        db.session.commit()
        return redirect(url_for("lines"))

    # jen hráči v soupise + jejich lajny
    roster = Roster.query.filter_by(team_id=current_user.team_id).all() if current_user.team_id else []
    assignments = {}
    if current_user.team_id:
        assignments = {a.slot: a.player_id for a in LineAssignment.query.filter_by(team_id=current_user.team_id).all()}
    return render_template("lines.html", roster=roster, assignments=assignments)

def _current_line_assignments():
    if not current_user.is_authenticated or not current_user.team_id:
        return {}

    assigns = {a.slot: a.player_id for a in LineAssignment.query.filter_by(team_id=current_user.team_id).all()}
    players = {p.id: p for p in Player.query.filter_by(team_id=current_user.team_id).all()}
    return {slot: players.get(pid) for slot, pid in assigns.items()}



def _compose_lines_pdf(title: str) -> str:
    # Build one-page PDF with current lines
    export_dir = app.config['EXPORT_FOLDER']
    page = Image.new("RGB", (595, 842), "white")  # A4 @72dpi
    draw = ImageDraw.Draw(page)
    try:
        font_title = ImageFont.truetype("arial.ttf", 18)
        font_h = ImageFont.truetype("arial.ttf", 14)
        font_b = ImageFont.truetype("arial.ttf", 12)
    except Exception:
        font_title = ImageFont.load_default()
        font_h = ImageFont.load_default()
        font_b = ImageFont.load_default()
    margin = 36
    y = margin
    draw.text((margin, y), title or "Sestava", fill=(0,0,0), font=font_title)
    y += 28
    assigns = _current_line_assignments()
    def nm(p):
        return p.name if p else "-"
    # Lines 1..4
    for line in range(1,5):
        draw.text((margin, y), f"{line}. lajna", fill=(0,0,0), font=font_h)
        y += 18
        lw = nm(assigns.get(f"L{line}LW"))
        c  = nm(assigns.get(f"L{line}C"))
        rw = nm(assigns.get(f"L{line}RW"))
        draw.text((margin, y), f"Útok: {lw} – {c} – {rw}", fill=(0,0,0), font=font_b)
        y += 16
        ld = nm(assigns.get(f"D{line}LD"))
        rd = nm(assigns.get(f"D{line}RD"))
        draw.text((margin, y), f"Obrana: {ld} – {rd}", fill=(0,0,0), font=font_b)
        y += 22
    # Goalies
    y += 8
    draw.text((margin, y), "Brankáři", fill=(0,0,0), font=font_h); y += 18
    g1 = nm(assigns.get("G1")); g2 = nm(assigns.get("G2"))
    draw.text((margin, y), f"G1: {g1}", fill=(0,0,0), font=font_b); y += 16
    draw.text((margin, y), f"G2: {g2}", fill=(0,0,0), font=font_b); y += 16
    # Save
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    token = uuid.uuid4().hex[:6]
    filename = f"lineup-{ts}-{token}.pdf"
    out_path = os.path.join(export_dir, filename)
    page.save(out_path, format="PDF")
    return filename


@app.route("/lines/export_pdf", methods=["POST"])
@coach_required
def export_lines_pdf():
    opponent = (request.form.get("opponent") or "").strip()
    date = (request.form.get("date") or datetime.now().strftime("%Y-%m-%d")).strip()
    # Title format: Sestava - Zápas - "souper" - datum
    title = f'Sestava - Zápas - "{opponent}" - {date}'
    filename = _compose_lines_pdf(title)
    sess = LineupSession(title=title, filename=filename, team_id=(current_user.team_id if current_user.is_authenticated else None))
    db.session.add(sess)
    db.session.commit()
    cleanup_exports()
    return redirect(url_for("drills_export_result", file=filename))


@app.route("/lineup-sessions")
@login_required
def lineup_sessions():
    lq = LineupSession.query
    if current_user.is_authenticated and current_user.team_id:
        lq = lq.filter(LineupSession.team_id == current_user.team_id)
    sessions = lq.order_by(LineupSession.created_at.desc()).all()
    return render_template("lineup_sessions.html", sessions=sessions)


@app.route("/lineup-sessions/delete/<int:sess_id>", methods=["POST"])
@coach_required
def delete_lineup_session(sess_id):
    sess = LineupSession.query.get_or_404(sess_id)
    # kontrola, že sestava patří k aktuálnímu týmu
    if sess.team_id != current_user.team_id:
        flash("Nemáš oprávnění smazat tuto sestavu.", "error")
        return redirect(url_for('lineup_sessions'))

    export_dir = app.config['EXPORT_FOLDER']
    fpath = os.path.join(export_dir, sess.filename)
    try:
        if os.path.isfile(fpath):
            os.remove(fpath)
    except Exception as e:
        app.logger.warning('Delete lineup export file failed: %s', e)

    db.session.delete(sess)
    db.session.commit()
    return redirect(url_for('lineup_sessions'))


@app.route("/drill/new")
@coach_required
def new_drill():
    return render_template("new_drill.html")

@app.route("/drill/save", methods=["POST"])
@coach_required
def save_drill():
    name = request.form.get("name")
    description = request.form.get("description")
    duration = request.form.get("duration")
    category = request.form.get("category")
    image_data = request.form.get("image_data")
    path_data = request.form.get("path_data")

    # pokud přišlo prázdné → nastavíme prázdné pole
    if not path_data:
        path_data = "[]"

    drill = Drill(
        name=name,
        description=description,
        duration=int(duration) if duration else None,
        category=category,
        image_data=image_data,
        path_data=path_data,   # uložíme JSON jako string
        team_id=(current_user.team_id if current_user.is_authenticated else None)
    )
    db.session.add(drill)
    db.session.commit()
    return redirect(url_for("drills"))

@app.route("/drills")
@login_required
def drills():
    q = db.session.query(Drill.category)
    if current_user.team_id:
        q = q.filter(Drill.team_id == current_user.team_id)
    categories = q.distinct().all()
    categories = [c[0] for c in categories if c[0]]
    return render_template("drills_categories.html", categories=categories)


@app.route("/drills/<category>")
@login_required
def drills_by_category(category):
    query = request.args.get("q", "")
    drills = Drill.query.filter(Drill.category == category)
    if current_user.team_id:
        drills = drills.filter(Drill.team_id == current_user.team_id)
    if query:
        drills = drills.filter(
            (Drill.name.ilike(f"%{query}%")) |
            (Drill.description.ilike(f"%{query}%"))
        )
    drills = drills.all()
    return render_template("drills_by_category.html", category=category, drills=drills, query=query)

@app.route("/drill/<int:drill_id>")
@login_required
def drill_detail(drill_id):
    drill = Drill.query.get_or_404(drill_id)
    if current_user.team_id and drill.team_id != current_user.team_id:
        flash('Toto cvičení nepatří do vašeho týmu.', 'error')
        return redirect(url_for('drills'))
    return render_template("drill_detail.html", drill=drill)

@app.route("/drill/delete/<int:drill_id>", methods=["POST"])
@coach_required
def delete_drill(drill_id):
    drill = Drill.query.get_or_404(drill_id)
    if current_user.team_id and drill.team_id != current_user.team_id:
        flash('Není povoleno mazat cvičení jiného týmu.', 'error')
        return redirect(url_for('drills'))
    db.session.delete(drill)
    db.session.commit()
    return redirect(url_for("drills"))


# --- Výběr a export tréninků do PDF ---
@app.route("/drills/select")
def drills_select():
    q = request.args.get("q", "").strip()
    qry = Drill.query
    if current_user.is_authenticated and current_user.team_id:
        qry = qry.filter(Drill.team_id == current_user.team_id)
    if q:
        like = f"%{q}%"
        qry = qry.filter((Drill.name.ilike(like)) | (Drill.description.ilike(like)) | (Drill.category.ilike(like)))
    drills = qry.order_by(Drill.category.asc().nullsfirst(), Drill.name.asc()).all()
    default_title = f"Tréninková jednotka {datetime.now().strftime('%Y-%m-%d')}"
    return render_template("drills_select.html", drills=drills, query=q, default_title=default_title)


def _decode_image(data_url: str) -> Image.Image | None:
    try:
        if not data_url:
            return None
        if "," in data_url:
            b64 = data_url.split(",", 1)[1]
        else:
            b64 = data_url
        raw = base64.b64decode(b64)
        im = Image.open(io.BytesIO(raw))
        return im.convert("RGBA")
    except Exception:
        return None


def _compose_page(drill: Drill, im: Image.Image | None, page_size=(595, 842)) -> Image.Image:
    # A4 @ 72 DPI by default: 595x842 pt
    pg = Image.new("RGB", page_size, "white")
    draw = ImageDraw.Draw(pg)
    # Header text
    title = drill.name or "Bez názvu"
    sub = []
    if drill.category:
        sub.append(f"Kategorie: {drill.category}")
    if drill.duration:
        sub.append(f"Doba: {drill.duration} min")
    subline = "  •  ".join(sub)
    desc = (drill.description or "").strip()
    # Fonts (fallback to default)
    try:
        font_title = ImageFont.truetype("arial.ttf", 18)
        font_sub = ImageFont.truetype("arial.ttf", 12)
        font_desc = ImageFont.truetype("arial.ttf", 12)
    except Exception:
        font_title = ImageFont.load_default()
        font_sub = ImageFont.load_default()
        font_desc = ImageFont.load_default()
    margin = 36  # 0.5 inch
    y = margin
    draw.text((margin, y), title, fill=(0, 0, 0), font=font_title)
    y += 24
    if subline:
        draw.text((margin, y), subline, fill=(0, 0, 0), font=font_sub)
        y += 18
    # Description (max 6 lines)
    if desc:
        max_width = page_size[0] - 2 * margin
        words = desc.split()
        lines = []
        cur = ""
        for w in words:
            test = (cur + " " + w).strip()
            if draw.textlength(test, font=font_desc) <= max_width:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
            if len(lines) >= 6:
                break
        if cur and len(lines) < 6:
            lines.append(cur)
        for line in lines:
            draw.text((margin, y), line, fill=(0, 0, 0), font=font_desc)
            y += 16
        y += 8
    # Image area
    top = y
    bottom = page_size[1] - margin
    left = margin
    right = page_size[0] - margin
    if im is not None:
        # flatten alpha onto white
        if im.mode == "RGBA":
            bg = Image.new("RGB", im.size, "white")
            bg.paste(im, mask=im.split()[3])
            im_rgb = bg
        else:
            im_rgb = im.convert("RGB")
        box_w = right - left
        box_h = bottom - top
        # scale preserving ratio
        iw, ih = im_rgb.size
        scale = min(box_w / iw, box_h / ih)
        nw = int(iw * scale)
        nh = int(ih * scale)
        im_resized = im_rgb.resize((nw, nh), Image.LANCZOS)
        ox = left + (box_w - nw) // 2
        oy = top + (box_h - nh) // 2
        pg.paste(im_resized, (ox, oy))
    else:
        note = "(Bez náhledu cvičení)"
        draw.text((left, top), note, fill=(0, 0, 0), font=font_sub)
    return pg


@app.route("/drills/export_pdf", methods=["POST"])
@coach_required
def export_drills_pdf():
    ids = request.form.getlist("drill_ids")
    session_title = (request.form.get("session_title") or "").strip()
    if not ids:
        return redirect(url_for("drills_select"))
    drills = Drill.query.filter(Drill.id.in_([int(i) for i in ids])).order_by(Drill.category.asc().nullsfirst(), Drill.name.asc()).all()
    if not drills:
        return redirect(url_for("drills_select"))
    pages: list[Image.Image] = []
    for d in drills:
        im = _decode_image(d.image_data or "")
        page = _compose_page(d, im)
        pages.append(page)
    # Ulož PDF do chráněného adresáře
    export_dir = app.config['EXPORT_FOLDER']
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    token = uuid.uuid4().hex[:8]
    filename = f"drills-{ts}-{token}.pdf"
    path = os.path.join(export_dir, filename)
    if len(pages) == 1:
        pages[0].save(path, format="PDF")
    else:
        pages[0].save(path, save_all=True, append_images=pages[1:], format="PDF")
    # Ulož session (název + seznam drillů)
    if not session_title:
        session_title = f"Tréninková jednotka {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    sess = TrainingSession(title=session_title, filename=filename, drill_ids=",".join(str(d.id) for d in drills), team_id=(current_user.team_id if current_user.is_authenticated else None))
    db.session.add(sess)
    db.session.commit()
    # Úklid starých exportů (ponecháme pouze soubory navázané na session a čerstvé orphan soubory do retention)
    cleanup_exports()
    # Přesměruj na výsledkovou stránku s odkazy (download / WhatsApp)
    return redirect(url_for("drills_export_result", file=filename))


def cleanup_exports(retention_days: int = 14):
    export_dir = app.config['EXPORT_FOLDER']
    try:
        os.makedirs(export_dir, exist_ok=True)
        # seznam souborů referencovaných sessions
        referenced = set(s.filename for s in TrainingSession.query.all())
        try:
            for s in LineupSession.query.all():
                referenced.add(s.filename)
        except Exception as e:
            app.logger.warning('List lineup sessions failed in cleanup_exports: %s', e)
        cutoff = datetime.now() - timedelta(days=retention_days)
        for fname in os.listdir(export_dir):
            if not fname.lower().endswith('.pdf'):
                continue
            fpath = os.path.join(export_dir, fname)
            try:
                st = os.stat(fpath)
                mtime = datetime.fromtimestamp(st.st_mtime)
            except Exception as e:
                app.logger.warning('Stat export file failed: %s', e)
                continue
            # nemaž referencované soubory
            if fname in referenced:
                continue
            # orphan soubor starší než retention smaž
            if mtime < cutoff:
                try:
                    os.remove(fpath)
                except Exception as e:
                    app.logger.warning('Remove old export failed: %s', e)
    except Exception as e:
        app.logger.warning('cleanup_exports failed: %s', e)
        return


@app.route("/drill-sessions")
def drill_sessions():
    sq = TrainingSession.query
    if current_user.is_authenticated and current_user.team_id:
        sq = sq.filter(TrainingSession.team_id == current_user.team_id)
    sessions = sq.order_by(TrainingSession.created_at.desc()).all()
    # mapování ID -> Drill pro zobrazení
    drills_by_id = {d.id: d for d in Drill.query.all()}
    return render_template("drills_sessions.html", sessions=sessions, drills_by_id=drills_by_id)

@app.route('/calendar/add', methods=['POST'])
@coach_required
def calendar_add():
    day_s = (request.form.get('day') or '').strip()
    time_s = (request.form.get('time') or '').strip()
    title = (request.form.get('title') or 'Trénink').strip() or 'Trénink'
    from datetime import date
    try:
        d = date.fromisoformat(day_s)
    except Exception as e:
        app.logger.warning('calendar_add invalid date: %s', e)
        flash('Neplatné datum.', 'error')
        return redirect(request.referrer or url_for('home'))
    ev = TrainingEvent(team_id=current_user.team_id, day=d, time=time_s[:10], title=title[:200], kind=(request.form.get('kind') or 'training')[:20])
    db.session.add(ev)
    db.session.commit()
    flash('Trénink byl přidán do kalendáře.', 'success')
    return redirect(url_for('home', year=d.year, month=d.month))


@app.route('/calendar/update', methods=['POST'])
@coach_required
def calendar_update():
    try:
        ev_id = int(request.form.get('id') or '0')
    except Exception as e:
        app.logger.warning('calendar_update invalid id: %s', e)
        ev_id = 0
    ev = TrainingEvent.query.get(ev_id)
    if not ev or ev.team_id != current_user.team_id:
        flash('Událost nebyla nalezena.', 'error')
        return redirect(request.referrer or url_for('home'))
    title = (request.form.get('title') or ev.title).strip()
    time_s = (request.form.get('time') or (ev.time or '')).strip()
    kind = (request.form.get('kind') or (ev.kind or 'training')).strip()
    ev.title = title[:200] or ev.title
    ev.time = time_s[:10]
    ev.kind = kind if kind in ('training','match') else (ev.kind or 'training')
    db.session.commit()
    flash('Událost byla upravena.', 'success')
    return redirect(url_for('home', year=ev.day.year, month=ev.day.month))


@app.route('/calendar/delete', methods=['POST'])
@coach_required
def calendar_delete():
    try:
        ev_id = int(request.form.get('id') or '0')
    except Exception as e:
        app.logger.warning('calendar_delete invalid id: %s', e)
        ev_id = 0
    ev = TrainingEvent.query.get(ev_id)
    if not ev or ev.team_id != current_user.team_id:
        flash('Událost nebyla nalezena.', 'error')
        return redirect(request.referrer or url_for('home'))
    y, m = ev.day.year, ev.day.month
    db.session.delete(ev)
    db.session.commit()
    flash('Událost byla smazána.', 'success')
    return redirect(url_for('home', year=y, month=m))



@app.route("/drill-sessions/delete/<int:sess_id>", methods=["POST"])
@coach_required
def delete_drill_session(sess_id):
    sess = TrainingSession.query.get_or_404(sess_id)
    if sess.team_id and sess.team_id != current_user.team_id:
        flash('Není povoleno mazat záznamy jiného týmu.', 'error')
        return redirect(url_for('drill_sessions'))
    # odeber soubor, pokud existuje
    export_dir = app.config['EXPORT_FOLDER']
    fpath = os.path.join(export_dir, sess.filename)
    try:
        if os.path.isfile(fpath):
            os.remove(fpath)
    except Exception:
        pass
    db.session.delete(sess)
    db.session.commit()
    return redirect(url_for('drill_sessions'))


@app.route("/drills/export_result")
def drills_export_result():
    filename = request.args.get("file")
    if not filename:
        return redirect(url_for("drills_select"))
    file_url = url_for('download_export', filename=filename, _external=False)
    # absolutní URL pro sdílení (pokud je aplikace dostupná zvenčí)
    try:
        abs_url = url_for('download_export', filename=filename, _external=True)
    except Exception as e:
        app.logger.warning('Building absolute export URL failed: %s', e)
        abs_url = file_url
    return render_template("drills_export_result.html", filename=filename, file_url=file_url, abs_url=abs_url)


@app.route('/exports/<path:filename>')
@login_required
def download_export(filename):
    # Allow download only if export belongs to current user's team
    allowed = False
    if current_user.team_id:
        ts = TrainingSession.query.filter_by(team_id=current_user.team_id, filename=filename).first()
        ls = LineupSession.query.filter_by(team_id=current_user.team_id, filename=filename).first()
        allowed = bool(ts or ls)
    if not allowed:
        flash('Soubor nepatří do vašeho týmu.', 'error')
        return redirect(url_for('home'))
    base = os.path.abspath(app.config['EXPORT_FOLDER'])
    fpath = os.path.abspath(os.path.join(base, filename))
    if not fpath.startswith(base + os.sep):
        flash('Neplatný název souboru.', 'error')
        return redirect(url_for('home'))
    try:
        return send_file(fpath, mimetype='application/pdf', as_attachment=False, max_age=0)
    except Exception as e:
        app.logger.warning('Download export failed: %s', e)
        flash('Soubor nebyl nalezen.', 'error')
        return redirect(url_for('home'))


# --- Admin: Audit log ---
@app.route('/admin/audit-log')
@login_required
def audit_log():
    if not current_user.is_team_admin:
        flash('Přístup jen pro týmové administrátory.', 'error')
        return redirect(url_for('home'))
    logs = []
    users_by_id = {}
    if current_user.team_id:
        logs = AuditLog.query.filter_by(team_id=current_user.team_id).order_by(AuditLog.created_at.desc()).limit(200).all()
        # Natahni aktéry/cíle do mapy
        ids = set()
        for l in logs:
            if l.actor_user_id:
                ids.add(l.actor_user_id)
            if l.target_user_id:
                ids.add(l.target_user_id)
        if ids:
            for u in User.query.filter(User.id.in_(list(ids))).all():
                users_by_id[u.id] = u
    return render_template('audit_log.html', logs=logs, users_by_id=users_by_id)

@app.route("/delete_from_roster/<int:roster_id>", methods=["POST"])
@coach_required
def delete_from_roster(roster_id):
    roster_entry = Roster.query.get(roster_id)
    if roster_entry and roster_entry.team_id == current_user.team_id:
        db.session.delete(roster_entry)
        db.session.commit()
    return redirect(url_for("roster"))

# --- Úprava hráče ---
@app.route("/edit_player/<int:player_id>", methods=["GET", "POST"])
@coach_required
def edit_player(player_id):
    player = Player.query.get_or_404(player_id)
    if player.team_id != current_user.team_id:
        flash('Není povoleno upravovat hráče jiného týmu.', 'error')
        return redirect(url_for('players'))

    if request.method == "POST":
        # aktualizace údajů
        player.name = request.form.get("name")
        player.position = request.form.get("position")
        db.session.commit()
        return redirect(url_for("players"))

    return render_template("edit_player.html", player=player)



# --- Spuštění ---
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
