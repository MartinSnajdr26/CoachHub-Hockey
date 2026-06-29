import os

DEV_TEMP_SECRET = 'coachhub-dev-admin'
BOOTSTRAP_FLAG = 'coachhub_owner_admin_bootstrap'


def is_dev_mode(app) -> bool:
    try:
        return bool(
            app.config.get('IS_DEV')
            or getattr(app, 'debug', False)
            or os.getenv('FLASK_DEBUG') == '1'
            or os.getenv('DEBUG') == '1'
        )
    except Exception:
        return bool(os.getenv('FLASK_DEBUG') == '1' or os.getenv('DEBUG') == '1')


def ensure_owner_secret(app):
    """Ensure an owner secret exists in development and print it once."""
    if not is_dev_mode(app):
        return app.config.get('ADMIN_SECRET_KEY')

    secret = (app.config.get('ADMIN_SECRET_KEY') or '').strip() or (os.getenv('ADMIN_SECRET_KEY') or '').strip()
    if not secret:
        secret = (os.getenv('OWNER_ACCESS_KEY') or '').strip()
    if not secret:
        secret = DEV_TEMP_SECRET

    if not app.config.get('ADMIN_SECRET_KEY'):
        app.config['ADMIN_SECRET_KEY'] = secret

    state = app.extensions.setdefault('coachhub_owner_admin', {})
    if not state.get(BOOTSTRAP_FLAG):
        state[BOOTSTRAP_FLAG] = True
        if not state.get('is_printed'):
            state['is_printed'] = True
            print(
                "====================================\n"
                "CoachHub Owner Admin\n\n"
                "Owner Login:\n"
                "http://127.0.0.1:5000/owner/login\n\n"
                "Temporary Owner Password:\n"
                f"{secret}\n"
                "===================================="
            )
    return secret


def get_owner_secret(app):
    secret = (app.config.get('ADMIN_SECRET_KEY') or '').strip()
    if secret:
        return secret
    if is_dev_mode(app):
        return ensure_owner_secret(app)
    return None
