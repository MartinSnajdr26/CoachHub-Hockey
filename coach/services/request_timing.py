"""Central per-request performance logging (Phase 2 of the production audit).

Registers before/after_request hooks that time every request with
``time.perf_counter`` and log method, path, status, duration (ms), endpoint,
query count and the current team id (never any PII, tokens, form data, cookies
or session contents). Requests slower than ``SLOW_REQUEST_THRESHOLD_MS``
(default 1000) are logged at WARNING so they surface in the PythonAnywhere
server log; faster ones at INFO. All hooks are fully guarded — a missing timing
value or a logging error can never break the response.
"""
import logging
import os
import time

from flask import g, has_request_context, request, session
from sqlalchemy import event
from sqlalchemy.engine import Engine

_DEFAULT_THRESHOLD_MS = 1000


def _threshold_ms() -> int:
    try:
        return int(os.getenv('SLOW_REQUEST_THRESHOLD_MS', str(_DEFAULT_THRESHOLD_MS)))
    except (TypeError, ValueError):
        return _DEFAULT_THRESHOLD_MS


# Count executed statements per request. Attached to the SQLAlchemy Engine class
# (not a specific engine, which would require an app context at import time) so
# it works for every engine, including the in-memory test DB. It is a no-op
# outside a request context and can never raise into the DB layer.
@event.listens_for(Engine, 'before_cursor_execute')
def _count_query(conn, cursor, statement, parameters, context, executemany):
    try:
        if has_request_context():
            g._perf_query_count = getattr(g, '_perf_query_count', 0) + 1
    except Exception:
        pass


def register_request_timing(app):
    """Wire the timing hooks onto ``app``. Uses the existing application logger
    so slow-request warnings are visible wherever the app already logs."""
    logger = app.logger

    @app.before_request
    def _perf_start():
        try:
            g._perf_start = time.perf_counter()
            g._perf_query_count = 0
        except Exception:
            pass

    @app.after_request
    def _perf_end(response):
        try:
            start = getattr(g, '_perf_start', None)
            if start is None:
                return response
            dur_ms = (time.perf_counter() - start) * 1000.0

            team = None
            try:
                tid = session.get('team_id')
                team = int(tid) if tid is not None else None
            except Exception:
                team = None

            detail = (
                '%s %s -> %s %.1fms q=%s ep=%s team=%s' % (
                    request.method,
                    request.path,
                    response.status_code,
                    dur_ms,
                    getattr(g, '_perf_query_count', 0),
                    request.endpoint or '-',
                    team if team is not None else '-',
                )
            )
            if dur_ms >= _threshold_ms():
                logger.warning('[perf] SLOW %s', detail)
            elif logger.isEnabledFor(logging.INFO):
                logger.info('[perf] %s', detail)
        except Exception:
            # Timing/logging must never break the actual response.
            pass
        return response
