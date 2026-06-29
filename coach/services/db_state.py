from sqlalchemy import inspect
from sqlalchemy.exc import DatabaseError, OperationalError, ProgrammingError

from coach.extensions import db


_MISSING_DB_MARKERS = (
    'no such table',
    'does not exist',
    'undefined table',
    'unknown table',
    'database is not initialized',
    'unable to open database file',
)


def is_database_not_ready_error(exc: Exception) -> bool:
    if not isinstance(exc, (OperationalError, ProgrammingError, DatabaseError)):
        return False
    text = str(exc).lower()
    return any(marker in text for marker in _MISSING_DB_MARKERS)


def log_db_not_ready_once(app, key: str, exc: Exception, message: str) -> None:
    flags = app.extensions.setdefault('coachhub_db_warnings', set())
    if key in flags:
        return
    flags.add(key)
    try:
        app.logger.warning('%s: %s', message, exc)
    except Exception:
        pass


def has_table(table_name: str) -> bool:
    try:
        return inspect(db.engine).has_table(table_name)
    except Exception:
        return False


def create_missing_dev_tables(app) -> None:
    if not app.config.get('IS_DEV') or app.config.get('TESTING'):
        return
    if str(app.config.get('AUTO_CREATE_DEV_DB', '1')).lower() in ('0', 'false', 'no', 'off'):
        return
    try:
        if not has_table('team'):
            with app.app_context():
                db.create_all()
                app.logger.warning('Development database tables were missing and have been created.')
    except Exception as exc:
        if is_database_not_ready_error(exc):
            log_db_not_ready_once(app, 'dev-create-all-failed', exc, 'Development database initialization failed')
        else:
            raise
