import os
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


def client_ip():
    """Rate-limit key = the real client IP.

    Behind PythonAnywhere's proxy the app is wrapped in ProxyFix (see app.py), so
    ``request.remote_addr`` is the true client IP (the right-most, proxy-appended
    X-Forwarded-For entry) rather than the shared proxy IP. Client-supplied
    forwarded headers therefore cannot spoof or share a bucket. This is a thin,
    named wrapper over get_remote_address so the intent is explicit and testable.
    """
    return get_remote_address()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
MIGRATIONS_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', 'migrations'))

# Lazy extensions
db = SQLAlchemy()
migrate = Migrate(directory=MIGRATIONS_DIR)
login_manager = LoginManager()
bcrypt = Bcrypt()
csrf = CSRFProtect()
# Default limits are a GENEROUS backstop for ordinary application traffic, NOT the
# primary abuse control. Flask-Limiter applies these PER-ROUTE, PER-KEY, and the
# Flask `static` endpoint is auto-exempt. `/sw.js` and `/favicon.ico` are
# explicitly exempted in app.py / public.py (automatic asset requests). The real
# abuse protection lives on the risky routes: login, owner login, team creation
# (strict per-route limits, keyed by client IP). A runaway client/loop is still
# caught by these backstops.
#   Previous default was 200/day + 50/hour  ← too low; normal PWA use + a shared
#   proxy IP (no ProxyFix) meant unrelated users collided in one per-route bucket.
limiter = Limiter(client_ip, default_limits=["3000 per day", "300 per hour"])

