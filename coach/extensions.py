import os
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
MIGRATIONS_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', 'migrations'))

# Lazy extensions
db = SQLAlchemy()
migrate = Migrate(directory=MIGRATIONS_DIR)
login_manager = LoginManager()
bcrypt = Bcrypt()
csrf = CSRFProtect()
limiter = Limiter(get_remote_address, default_limits=["200 per day", "50 per hour"])

