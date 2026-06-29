"""Test-suite safety net for the SQLAlchemy engine binding.

Why this exists
---------------
`.env` sets ``DB_URL=sqlite:///coach/dev.db`` and ``APP_ENV=dev``. Importing
``coach.app`` therefore binds the SQLAlchemy engine to the real ``dev.db`` at
import time (``create_missing_dev_tables`` -> ``inspect(db.engine)``).

Flask-SQLAlchemy caches that engine. Each test's ``setUp`` does
``app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')`` *after* the
engine is already cached, so the override is silently ignored and the test's
``db.drop_all()`` / ``db.create_all()`` run against the developer's real
``dev.db`` — destroying its data on the first ``drop_all()``.

This module rebinds the engine to an in-memory database ONCE, before any test
runs (while the app is still mutable), and then hard-asserts the binding before
every test. A stray ``drop_all()`` can never reach a file-backed database again.
"""
import pytest

from coach.app import app
from coach.extensions import db

MEMORY_URI = "sqlite:///:memory:"


def _rebind_to_memory():
    """Point the app at :memory: and rebuild the engine for that URI.

    Must run before the app handles its first request: ``init_app`` registers a
    teardown handler, which Flask forbids once setup is finished. We therefore
    call this exactly once, from the session-scoped fixture below."""
    app.config["SQLALCHEMY_DATABASE_URI"] = MEMORY_URI
    app.config["SQLALCHEMY_BINDS"] = {}
    app.config["TESTING"] = True
    # Dispose the engine bound at import (dev.db) and drop the prior registration
    # so init_app can rebuild the engine map from the :memory: config.
    engines = getattr(db, "_app_engines", {}).get(app)
    if engines:
        for engine in list(engines.values()):
            try:
                engine.dispose()
            except Exception:
                pass
    app.extensions.pop("sqlalchemy", None)
    if hasattr(db, "_app_engines"):
        db._app_engines.pop(app, None)
    db.init_app(app)


@pytest.fixture(autouse=True, scope="session")
def _force_in_memory_db():
    _rebind_to_memory()
    yield


@pytest.fixture(autouse=True)
def _guard_against_real_db():
    """Per-test guard: refuse to run if the engine is bound to a real database."""
    with app.app_context():
        url = str(db.engine.url)
    assert ":memory:" in url, (
        "Refusing to run: test DB engine is bound to %r, not an in-memory "
        "database. Running would risk db.drop_all() destroying real data." % url
    )
    yield
