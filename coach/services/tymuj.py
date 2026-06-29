"""Týmuj ICS calendar integration — first-class, cache-backed, observable.

Design mirrors the League integration:
  * refresh_cache()      — fetch + parse + store (manual / test / refresh only).
  * diagnostic_refresh() — full pipeline trace for the owner debug page.
  * get_cached_events()/get_cached_participants()/get_status() — READ-ONLY,
    never hit the network. Dashboard, attendance and import use these only.

The cache is the source of truth. It is stored as a single AuditEvent row
(event='tymuj.cache') per team holding a versioned JSON payload — no schema
migration required. The last successful payload is preserved across failures.
"""
import hashlib
import http.client
import json
import logging
import os
import re
import socket
import time
import unicodedata
import urllib.error
import urllib.request  # noqa: F401  (kept as a stable monkeypatch target for tests)
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

from coach.extensions import db
from coach.models import AttendanceEntry, AuditEvent, Player, Team
from coach.services.logging import log_event
from coach.services.url_safety import UnsafeUrlError, validate_public_http_url, safe_urlopen

logger = logging.getLogger(__name__)

CACHE_EVENT = 'tymuj.cache'
# Týmuj's api2.tymuj.cz generates the ICS on demand and is slow to first byte
# (~30s observed). urllib applies one socket timeout to connect AND read, so the
# timeout must comfortably exceed that latency. Tunable via env for ops.
TIMEOUT = int(os.getenv('TYMUJ_TIMEOUT', '45'))            # first attempt (seconds)
RETRY_TIMEOUT = int(os.getenv('TYMUJ_RETRY_TIMEOUT', '60'))  # single read-timeout retry
RETRY_BACKOFF = float(os.getenv('TYMUJ_RETRY_BACKOFF', '2'))  # seconds before retry
MAX_BYTES = 3 * 1024 * 1024           # cap ICS download size (parity with league)
MAX_REDIRECTS = 3
PARSER_VERSION = 2                    # bump when the normalized event shape changes
CACHE_SCHEMA = 2                      # bump when the cache payload shape changes
STALE_AFTER_SECONDS = 7 * 24 * 3600  # cache older than this is flagged stale
USER_AGENT = "CoachHubHockey/1.0 (+https://coachhubhockey.com; tymuj ICS widget)"

FAIL_MESSAGE = 'Týmuj data could not be refreshed. Showing last saved data.'

_FAILURE_LABELS = {
    'connect_timeout': 'Connection timeout',
    'read_timeout': 'Read timeout',
    'dns_failure': 'DNS failure',
    'http_error': 'HTTP error',
    'too_large': 'Oversized response',
    'incomplete_read': 'Incomplete read',
    'ssrf_blocked': 'Blocked by SSRF protection',
    'invalid_url': 'Invalid URL',
    'connection_error': 'Connection error',
}

# Response headers safe to surface/store for diagnostics (no auth/cookies).
_SAFE_HEADER_KEYS = ('Content-Type', 'Content-Length', 'Transfer-Encoding',
                     'Content-Encoding', 'Server', 'Cache-Control', 'Connection',
                     'Date', 'Last-Modified', 'Age', 'Via')


class IcsFetchError(ValueError):
    """A classified ICS download failure (ValueError-compatible for callers).

    `reason` is a stable machine code: invalid_url | ssrf_blocked | dns_failure
    | connect_timeout | read_timeout | incomplete_read | http_error | too_large
    | connection_error."""

    def __init__(self, reason, detail='', *, status=None, headers=None,
                 bytes_read=None, retry_attempted=False):
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail or reason
        self.status = status
        self.headers = headers or {}
        self.bytes_read = bytes_read
        self.retry_attempted = retry_attempted


def _safe_headers(hdrs):
    if not hdrs:
        return {}
    out = {}
    for k in _SAFE_HEADER_KEYS:
        try:
            v = hdrs.get(k)
        except Exception:
            v = None
        if v:
            out[k] = v
    return out


def _mask_url(url):
    """scheme://host/<path>/****.ics — masks the secret calendar token in the
    path (and drops any query) so URLs are safe to show in owner/admin views."""
    try:
        p = urlsplit(url or '')
        path = p.path or ''
        head, _, tail = path.rpartition('/')
        if tail:
            if '.' in tail:
                base, ext = tail.rsplit('.', 1)
                masked = (base[:3] + '****') if base else '****'
                tail = masked + '.' + ext
            else:
                tail = (tail[:3] + '****') if len(tail) > 3 else '****'
            path = (head + '/' + tail) if head else ('/' + tail)
        return '%s://%s%s' % (p.scheme or '?', p.netloc or '', path)
    except Exception:
        return '(hidden)'

# SUMMARY keywords that mark an entry as a game/match (otherwise it is a practice)
_GAME_RE = re.compile(
    r'(z[aá]pas|utk[aá]n|turnaj|poh[aá]r|p[řr][aá]tel|friendly|\bmatch\b|\bgame\b|\bcup\b)',
    re.I)


# ----------------------------- keys / helpers -----------------------------
def make_event_key(title: str, day: date, time_s: str, kind: str, source: str) -> str:
    payload = f"{source}|{day.isoformat()}|{time_s or ''}|{kind or 'training'}|{title or ''}".encode('utf-8')
    return hashlib.sha1(payload).hexdigest()


def _norm(s: str) -> str:
    s = unicodedata.normalize('NFKD', (s or '')).encode('ascii', 'ignore').decode('ascii')
    return ' '.join(s.lower().split())


def _classify_kind(summary: str) -> str:
    return 'match' if _GAME_RE.search(summary or '') else 'training'


def _parse_ics_datetime(value: str):
    if not value:
        return None
    value = value.strip()
    try:
        if value.endswith('Z'):
            return datetime.strptime(value, '%Y%m%dT%H%M%SZ')
        return datetime.strptime(value, '%Y%m%dT%H%M%S')
    except Exception:
        pass
    try:
        return datetime.strptime(value, '%Y%m%d').date()
    except Exception:
        return None


def _unfold_ics_lines(raw: str) -> list:
    lines = raw.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    unfolded = []
    for line in lines:
        if not line:
            continue
        if line[0] in (' ', '\t') and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def _extract_cn(head: str):
    for param in head.split(';')[1:]:
        if param.strip().upper().startswith('CN='):
            return param.split('=', 1)[1].strip().strip('"').strip()
    return None


# ----------------------------- fetch + decode -----------------------------
def _decode_ics(raw: bytes, content_type: str = ''):
    """Decode ICS bytes, honouring an explicit charset then Czech fallbacks."""
    enc = None
    m = re.search(r'charset=["\']?([\w-]+)', content_type or '', re.I)
    if m:
        enc = m.group(1)
    for cand in [enc, 'utf-8', 'cp1250', 'iso-8859-2']:
        if not cand:
            continue
        try:
            return raw.decode(cand), cand
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode('utf-8', errors='replace'), 'utf-8/replace'


def _fetch_once(url: str, timeout: int):
    """One ICS fetch attempt with SSRF protection, size cap and HTTP metadata.

    Connect-phase and read-phase errors are classified separately and raised as
    IcsFetchError. Returns (text, meta) on success."""
    ok, msg = validate_public_http_url(url)
    if not ok:
        raise IcsFetchError('invalid_url', msg)
    req_headers = {
        'User-Agent': USER_AGENT,
        'Accept': 'text/calendar, text/plain;q=0.9, */*;q=0.5',
        'Accept-Language': 'cs,en;q=0.8',
    }
    # ---- connect phase (safe_urlopen re-validates every redirect hop) ----
    try:
        resp = safe_urlopen(url, timeout=timeout, headers=req_headers, max_redirects=MAX_REDIRECTS)
    except UnsafeUrlError as e:
        raise IcsFetchError('ssrf_blocked', str(e))
    except urllib.error.HTTPError as e:
        raise IcsFetchError('http_error', 'HTTP %s %s' % (e.code, getattr(e, 'reason', '')),
                            status=e.code, headers=_safe_headers(getattr(e, 'headers', None)))
    except urllib.error.URLError as e:
        reason = getattr(e, 'reason', e)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise IcsFetchError('connect_timeout', 'Connection timed out after %ss' % timeout)
        if isinstance(reason, socket.gaierror):
            raise IcsFetchError('dns_failure', 'DNS lookup failed')
        raise IcsFetchError('connection_error', str(reason))
    except (socket.timeout, TimeoutError):
        raise IcsFetchError('connect_timeout', 'Connection timed out after %ss' % timeout)
    # ---- read phase ----
    status = getattr(resp, 'status', None)
    hdrs = getattr(resp, 'headers', None)
    safe_hdrs = _safe_headers(hdrs)
    ctype = hdrs.get('Content-Type', '') if hdrs else ''
    final_url = resp.geturl() if hasattr(resp, 'geturl') else url
    try:
        raw = resp.read(MAX_BYTES + 1)
    except (socket.timeout, TimeoutError):
        raise IcsFetchError('read_timeout', 'The read operation timed out after %ss' % timeout,
                            status=status, headers=safe_hdrs)
    except http.client.IncompleteRead as e:
        raise IcsFetchError('incomplete_read', 'Incomplete read (%d bytes)' % len(e.partial),
                            status=status, headers=safe_hdrs, bytes_read=len(e.partial))
    except Exception as e:
        raise IcsFetchError('connection_error', str(e), status=status, headers=safe_hdrs)
    finally:
        try:
            resp.close()
        except Exception:
            pass
    if len(raw) > MAX_BYTES:
        raise IcsFetchError('too_large', 'ICS odpověď je příliš velká (limit %d B).' % MAX_BYTES,
                            status=status, headers=safe_hdrs, bytes_read=len(raw))
    text, enc = _decode_ics(raw, ctype)
    meta = {
        'status': status,
        'content_type': ctype,
        'bytes': len(raw),
        'encoding': enc,
        'final_url': final_url,
        'redirected': bool(final_url and final_url != url),
        'timeout': timeout,
        'max_redirects': MAX_REDIRECTS,
        'headers': safe_hdrs,
        'retry_attempted': False,
    }
    return text, meta


def _fetch_ics_with_meta(url: str):
    """Fetch the ICS, retrying ONCE on a read timeout (only) with a short backoff
    and an extended timeout. Other failures are not retried. Returns (text, meta)."""
    try:
        return _fetch_once(url, TIMEOUT)
    except IcsFetchError as e:
        if e.reason != 'read_timeout':
            raise
        logger.warning('Týmuj read timed out (%ss); retrying once with %ss for %s',
                       TIMEOUT, RETRY_TIMEOUT, _mask_url(url))
        try:
            time.sleep(RETRY_BACKOFF)
        except Exception:
            pass
        try:
            text, meta = _fetch_once(url, RETRY_TIMEOUT)
            meta['retry_attempted'] = True
            return text, meta
        except IcsFetchError as e2:
            e2.retry_attempted = True
            raise e2


def _fetch_ics(url: str) -> str:
    """Backward-compatible text-only fetch (used by older callers/tests)."""
    text, _meta = _fetch_ics_with_meta(url)
    return text


def _error_info(exc) -> dict:
    """Normalize an exception into a diagnostics dict (no secrets)."""
    if isinstance(exc, IcsFetchError):
        return {
            'reason': exc.reason,
            'message': exc.detail,
            'status': exc.status,
            'headers': exc.headers,
            'bytes_read': exc.bytes_read,
            'retry_attempted': exc.retry_attempted,
        }
    return {'reason': 'error', 'message': str(exc), 'status': None,
            'headers': {}, 'bytes_read': None, 'retry_attempted': False}


# ----------------------------- parsing -----------------------------
def parse_ics(raw: str) -> dict:
    """Parse an ICS document into normalized events + participants + stats.

    Never raises on malformed input — invalid/incomplete VEVENTs are skipped,
    duplicates (same UID/RECURRENCE-ID/day/time) are collapsed."""
    events = []
    participants = {}
    seen = set()
    current = None
    for line in _unfold_ics_lines(raw or ''):
        if line == 'BEGIN:VEVENT':
            current = {}
            continue
        if line == 'END:VEVENT':
            if current is not None:
                ev, dedup_key = _normalize_event(current)
                if ev and dedup_key not in seen:
                    seen.add(dedup_key)
                    events.append(ev)
            current = None
            continue
        if ':' not in line:
            continue
        head, value = line.split(':', 1)
        name = head.split(';', 1)[0].strip().upper()
        # Participants are collected across the whole file (ATTENDEE/ORGANIZER CN).
        if name in ('ATTENDEE', 'ORGANIZER'):
            cn = _extract_cn(head)
            if cn:
                participants.setdefault(cn.lower(), cn)
        if current is not None:
            current.setdefault(name, value)  # first occurrence wins
    stats = {
        'event_count': len(events),
        'practice_count': sum(1 for e in events if e['kind'] == 'training' and not e['cancelled']),
        'game_count': sum(1 for e in events if e['kind'] == 'match' and not e['cancelled']),
        'cancelled_count': sum(1 for e in events if e['cancelled']),
        'recurring_count': sum(1 for e in events if e['recurring']),
        'participant_count': len(participants),
    }
    return {
        'events': events,
        'participants': sorted(participants.values(), key=lambda s: s.lower()),
        'stats': stats,
    }


def _normalize_event(props: dict):
    """Return (normalized_event | None, dedup_key)."""
    dtstart = _parse_ics_datetime(props.get('DTSTART', ''))
    summary = (props.get('SUMMARY', '') or '').strip()
    if not dtstart or not summary:
        return None, None
    if isinstance(dtstart, datetime):
        day = dtstart.date()
        time_s = dtstart.strftime('%H:%M')
    else:
        day = dtstart
        time_s = ''
    end_dt = _parse_ics_datetime(props.get('DTEND', ''))
    end_time = end_dt.strftime('%H:%M') if isinstance(end_dt, datetime) else ''
    status = (props.get('STATUS', '') or '').strip().upper()
    cancelled = (status == 'CANCELLED')
    recurring = bool((props.get('RRULE') or '').strip() or (props.get('RECURRENCE-ID') or '').strip())
    uid = (props.get('UID', '') or '').strip()
    rid = (props.get('RECURRENCE-ID', '') or '').strip()
    event = {
        'uid': uid,
        'day': day.isoformat(),
        'time': time_s,
        'end_time': end_time,
        'title': summary,
        'location': (props.get('LOCATION', '') or '').strip()[:200],
        'kind': _classify_kind(summary),
        'cancelled': cancelled,
        'recurring': recurring,
        'source': 'tymuj',
    }
    dedup_key = '%s|%s|%s|%s' % (uid or summary, rid, event['day'], time_s)
    return event, dedup_key


def parse_events(raw: str) -> list:
    """Backward-compatible: list of normalized event dicts."""
    return parse_ics(raw)['events']


def parse_participants(raw: str) -> list:
    """Backward-compatible: sorted participant display names."""
    return parse_ics(raw)['participants']


# ----------------------------- cache I/O -----------------------------
def _load_cache_payload(team_id: int) -> dict:
    row = AuditEvent.query.filter_by(team_id=team_id, event=CACHE_EVENT).first()
    if not row or not row.meta:
        return {}
    try:
        return json.loads(row.meta)
    except Exception:
        return {}


def _cache_payload(team_id: int) -> dict:
    """Read the cache payload, memoized per request to avoid duplicate JSON
    parsing when several widgets read it on one page."""
    if not team_id:
        return {}
    try:
        from flask import g, has_request_context
        if has_request_context():
            store = getattr(g, '_tymuj_cache', None)
            if store is None:
                store = {}
                g._tymuj_cache = store
            if team_id in store:
                return store[team_id]
            val = _load_cache_payload(team_id)
            store[team_id] = val
            return val
    except Exception:
        pass
    return _load_cache_payload(team_id)


def _write_cache(team_id: int, payload: dict) -> None:
    row = AuditEvent.query.filter_by(team_id=team_id, event=CACHE_EVENT).first()
    if not row:
        row = AuditEvent(event=CACHE_EVENT, team_id=team_id, role='coach')
        db.session.add(row)
    row.meta = json.dumps(payload, ensure_ascii=False)
    db.session.commit()
    try:
        from flask import g, has_request_context
        if has_request_context() and getattr(g, '_tymuj_cache', None) is not None:
            g._tymuj_cache.pop(team_id, None)
    except Exception:
        pass


def _validate_cache(payload: dict):
    if not payload:
        return False, 'cache is empty'
    if payload.get('cache_schema') != CACHE_SCHEMA:
        return False, 'schema %s != %s' % (payload.get('cache_schema'), CACHE_SCHEMA)
    if not isinstance(payload.get('events'), list):
        return False, 'events missing'
    stats = payload.get('stats') or {}
    if stats.get('event_count', 0) != len(payload.get('events') or []):
        return False, 'event_count mismatch'
    return True, 'ok'


def _build_success_payload(url: str, parsed: dict, meta: dict, prev: dict) -> dict:
    now = datetime.utcnow().isoformat()
    return {
        'cache_schema': CACHE_SCHEMA,
        'parser_version': PARSER_VERSION,
        'url_hash': hashlib.sha256((url or '').encode('utf-8')).hexdigest(),
        'events': parsed['events'],
        'participants': parsed['participants'],
        'stats': parsed['stats'],
        'http': meta,
        'updated_at': now,            # legacy alias for last_success (templates)
        'last_success': now,
        'last_failure': prev.get('last_failure') or prev.get('last_failed_at'),
        'last_error': None,
        'last_error_code': None,
        'last_http': meta,            # status + safe headers + retry flag
    }


# ----------------------------- refresh -----------------------------
def refresh_cache(team_id: int, url: str):
    """Fetch + parse + store. On failure keep the last good cache. Network is
    only ever touched here (manual save / test / refresh), never on render."""
    if not team_id or not url:
        return False, 'Není nastavena Týmuj ICS URL.'
    prev = _load_cache_payload(team_id)
    try:
        text, meta = _fetch_ics_with_meta(url)
        parsed = parse_ics(text)
        payload = _build_success_payload(url, parsed, meta, prev)
        _write_cache(team_id, payload)
        st = parsed['stats']
        log_event('integration.tymuj.success', team_id=team_id, role='coach', level='info',
                  message='Tymuj refresh succeeded',
                  meta={'events': st['event_count'], 'practices': st['practice_count'],
                        'games': st['game_count'], 'cancelled': st['cancelled_count'],
                        'participants': st['participant_count']})
        return True, 'Týmuj data byla načtena do lokální cache.'
    except Exception as e:
        db.session.rollback()
        info = _error_info(e)
        # Preserve last good events/participants — never overwrite with empty data.
        payload = dict(prev)
        payload['cache_schema'] = payload.get('cache_schema') or CACHE_SCHEMA
        payload['last_error'] = info['message'][:300]
        payload['last_error_code'] = info['reason']
        payload['last_failure'] = datetime.utcnow().isoformat()
        payload['last_failed_at'] = payload['last_failure']   # legacy alias (templates)
        payload['last_http'] = {'status': info['status'], 'headers': info['headers'],
                                'bytes_read': info['bytes_read'],
                                'retry_attempted': info['retry_attempted'],
                                'timeout': TIMEOUT, 'retry_timeout': RETRY_TIMEOUT}
        _write_cache(team_id, payload)
        log_event('integration.tymuj.failure', team_id=team_id, role='coach', level='error',
                  message=info['message'][:300],
                  meta={'reason': info['reason'], 'status': info['status'],
                        'retry_attempted': info['retry_attempted'],
                        'has_cache': bool(payload.get('events') or payload.get('participants'))})
        return False, FAIL_MESSAGE


# ----------------------------- read API (no network) -----------------------------
def get_cached_events(team_id: int, start_date: date, end_date: date,
                      include_cancelled: bool = False) -> list:
    out = []
    for item in _cache_payload(team_id).get('events', []) or []:
        if not include_cancelled and item.get('cancelled'):
            continue
        try:
            day = date.fromisoformat(item.get('day') or '')
        except Exception:
            continue
        if start_date <= day <= end_date:
            out.append({
                'day': day,
                'time': item.get('time') or '',
                'title': item.get('title') or '',
                'kind': item.get('kind') or 'training',
                'location': item.get('location') or '',
                'cancelled': bool(item.get('cancelled')),
                'source': 'tymuj',
            })
    return out


def get_cached_participants(team_id: int) -> list:
    return list(_cache_payload(team_id).get('participants', []) or [])


def _age_seconds(iso_ts):
    if not iso_ts:
        return None
    try:
        return int((datetime.utcnow() - datetime.fromisoformat(iso_ts)).total_seconds())
    except Exception:
        return None


def get_status(team_id: int) -> dict:
    payload = _cache_payload(team_id)
    stats = payload.get('stats') or {}
    last_success = payload.get('last_success') or payload.get('updated_at')
    last_failure = payload.get('last_failure') or payload.get('last_failed_at')
    cache_age = _age_seconds(last_success)
    events = payload.get('events', []) or []
    participants = payload.get('participants', []) or []
    return {
        # legacy keys consumed by existing templates — keep stable
        'updated_at': last_success,
        'last_error': payload.get('last_error'),
        'last_failed_at': last_failure,
        'events_count': stats.get('event_count', len(events)),
        'participants_count': stats.get('participant_count', len(participants)),
        'has_cache': bool(events or participants),
        # first-class observability
        'last_success': last_success,
        'last_failure': last_failure,
        'last_error_code': payload.get('last_error_code'),
        'cache_schema': payload.get('cache_schema'),
        'parser_version': payload.get('parser_version'),
        'cache_age_seconds': cache_age,
        'stale': (cache_age is None) or (cache_age > STALE_AFTER_SECONDS),
        'never_succeeded': not last_success,
        'timeout': TIMEOUT,
        'retry_timeout': RETRY_TIMEOUT,
        'stats': stats,
        'http': payload.get('http') or {},
        'last_http': payload.get('last_http') or {},
    }


# ----------------------------- owner debug + diagnostics -----------------------------
def _next_event(events: list, kind: str, today: date):
    cand = []
    for e in events:
        if e.get('cancelled') or (e.get('kind') or 'training') != kind:
            continue
        try:
            d = date.fromisoformat(e.get('day') or '')
        except Exception:
            continue
        if d >= today:
            cand.append((d, e.get('time') or '', e.get('title') or ''))
    cand.sort()
    if not cand:
        return None
    return ('%s %s %s' % (cand[0][0].isoformat(), cand[0][1], cand[0][2])).strip()


def get_debug_summary(team_id: int) -> dict:
    team = Team.query.get(team_id) if team_id else None
    payload = _cache_payload(team_id)
    status = get_status(team_id)
    events = payload.get('events') or []
    stats = payload.get('stats') or {}
    today = date.today()

    participants = payload.get('participants') or []
    existing = Player.query.filter_by(team_id=team_id).all() if team_id else []
    norm_existing = {_norm(p.name) for p in existing}
    norm_seen, normalized, duplicates = set(), [], 0
    for nm in participants:
        n = _norm(nm)
        is_dup = n in norm_existing or n in norm_seen
        if is_dup:
            duplicates += 1
        norm_seen.add(n)
        normalized.append({'name': nm, 'normalized': n, 'exists': n in norm_existing})

    window = get_cached_events(team_id, today - timedelta(days=45), today + timedelta(days=180))
    keys = [make_event_key(e['title'], e['day'], e.get('time') or '', e.get('kind') or 'training', 'tymuj')
            for e in window]
    attended = ({a.event_key for a in AttendanceEntry.query.filter_by(team_id=team_id).all()}
                if team_id else set())
    mapped = sum(1 for k in keys if k in attended)

    valid, vmsg = _validate_cache(payload) if payload else (False, 'cache is empty')
    return {
        'team': team,
        'team_id': team_id,
        'general': {
            'url_masked': _mask_url(team.tymuj_ics_url) if (team and team.tymuj_ics_url) else None,
            'enabled': bool(team and team.tymuj_ics_url),
            'last_refresh': status.get('last_success'),
            'last_failure': status.get('last_failure'),
            'last_error': status.get('last_error'),
            'last_error_code': status.get('last_error_code'),
            'failure_kind': _FAILURE_LABELS.get(status.get('last_error_code')),
            'cache_age_seconds': status.get('cache_age_seconds'),
            'parser_version': payload.get('parser_version'),
            'timeout': TIMEOUT,
            'retry_timeout': RETRY_TIMEOUT,
        },
        'diagnostics': {
            'timeout_configured': TIMEOUT,
            'retry_timeout': RETRY_TIMEOUT,
            'failure_kind': _FAILURE_LABELS.get(status.get('last_error_code')),
            'last_error_code': status.get('last_error_code'),
            'last_http': status.get('last_http') or {},
        },
        'http': payload.get('http') or {},
        'ics': {
            'event_count': stats.get('event_count', len(events)),
            'practices': stats.get('practice_count', 0),
            'games': stats.get('game_count', 0),
            'cancelled': stats.get('cancelled_count', 0),
            'recurring': stats.get('recurring_count', 0),
            'next_practice': _next_event(events, 'training', today),
            'next_game': _next_event(events, 'match', today),
        },
        'import': {'detected_players': len(participants), 'duplicates': duplicates,
                   'normalized': normalized[:60]},
        'attendance': {'mapped': mapped, 'missing': len(keys) - mapped, 'total': len(keys)},
        'cache': {'schema': payload.get('cache_schema'), 'timestamp': status.get('last_success'),
                  'stale': status.get('stale'), 'valid': valid, 'validation': vmsg},
        'status': status,
        'events_json': events,
        'participants_json': participants,
    }


def tymuj_debug_rows() -> list:
    rows = []
    for t in Team.query.order_by(Team.name.asc()).all():
        if t.tymuj_ics_url or _load_cache_payload(t.id):
            rows.append(get_debug_summary(t.id))
    return rows


def diagnostic_refresh(team_id: int):
    """Full pipeline with a step-by-step trace, for /owner/tymuj-debug.
    Performs a real fetch + parse + cache write; keeps last good cache on error."""
    trace = []
    team = Team.query.get(team_id) if team_id else None
    url = (team.tymuj_ics_url or '').strip() if team else ''
    trace.append({'step': 'URL loaded', 'ok': bool(url), 'value': _mask_url(url) if url else None})
    ok_url, msg = validate_public_http_url(url) if url else (False, 'Není nastavena Týmuj ICS URL.')
    trace.append({'step': 'URL validation', 'ok': ok_url, 'detail': msg or 'ok'})
    if not ok_url:
        return False, msg, trace
    prev = _load_cache_payload(team_id)
    try:
        trace.append({'step': 'HTTP request', 'ok': True, 'value': _mask_url(url),
                      'timeout': TIMEOUT, 'retry_timeout': RETRY_TIMEOUT})
        text, meta = _fetch_ics_with_meta(url)
        trace.append({'step': 'Response status', 'ok': True, 'value': meta.get('status'),
                      'redirected': meta.get('redirected'),
                      'retry_attempted': meta.get('retry_attempted'),
                      'headers': meta.get('headers')})
        trace.append({'step': 'Download size', 'ok': True, 'value': meta.get('bytes')})
        trace.append({'step': 'Encoding', 'ok': True, 'value': meta.get('encoding'),
                      'content_type': meta.get('content_type')})
        trace.append({'step': 'Parser', 'ok': True, 'value': 'ics v%d' % PARSER_VERSION})
        parsed = parse_ics(text)
        st = parsed['stats']
        trace.append({'step': 'Events parsed', 'ok': True, 'count': st['event_count']})
        trace.append({'step': 'Practices parsed', 'ok': True, 'count': st['practice_count']})
        trace.append({'step': 'Games parsed', 'ok': True, 'count': st['game_count']})
        trace.append({'step': 'Cancelled parsed', 'ok': True, 'count': st['cancelled_count']})
        trace.append({'step': 'Recurring parsed', 'ok': True, 'count': st['recurring_count']})
        trace.append({'step': 'Players detected', 'ok': True, 'count': st['participant_count']})
        payload = _build_success_payload(url, parsed, meta, prev)
        valid, vmsg = _validate_cache(payload)
        trace.append({'step': 'Cache validation', 'ok': valid, 'detail': vmsg})
        if not valid:
            raise ValueError(vmsg)
        _write_cache(team_id, payload)
        trace.append({'step': 'Cache write', 'ok': True, 'schema': CACHE_SCHEMA})
        today = date.today()
        window = get_cached_events(team_id, today - timedelta(days=45), today + timedelta(days=180))
        keys = [make_event_key(e['title'], e['day'], e.get('time') or '', e.get('kind') or 'training', 'tymuj')
                for e in window]
        attended = {a.event_key for a in AttendanceEntry.query.filter_by(team_id=team_id).all()}
        mapped = sum(1 for k in keys if k in attended)
        trace.append({'step': 'Attendance mapping', 'ok': True, 'count': len(keys),
                      'mapped': mapped, 'missing': len(keys) - mapped})
        trace.append({'step': 'Dashboard model', 'ok': True, 'count': len(window)})
        existing = Player.query.filter_by(team_id=team_id).all()
        norm_existing = {_norm(p.name) for p in existing}
        detected = parsed['participants']
        already = sum(1 for nm in detected if _norm(nm) in norm_existing)
        trace.append({'step': 'Import model', 'ok': True, 'detected': len(detected),
                      'already_in_roster': already, 'new': len(detected) - already})
        log_event('integration.tymuj.debug.diagnostic_refresh', team_id=team_id, role='owner',
                  level='info', message='Owner tymuj diagnostic refresh completed',
                  meta={'ok': True, 'events': st['event_count'], 'participants': st['participant_count']})
        return True, 'Diagnostic refresh completed.', trace
    except Exception as exc:
        db.session.rollback()
        info = _error_info(exc)
        # Preserve last good cache; never write empty data on failure.
        payload = dict(prev)
        payload['cache_schema'] = payload.get('cache_schema') or CACHE_SCHEMA
        payload['last_error'] = info['message'][:300]
        payload['last_error_code'] = info['reason']
        payload['last_failure'] = datetime.utcnow().isoformat()
        payload['last_failed_at'] = payload['last_failure']
        payload['last_http'] = {'status': info['status'], 'headers': info['headers'],
                                'bytes_read': info['bytes_read'],
                                'retry_attempted': info['retry_attempted'],
                                'timeout': TIMEOUT, 'retry_timeout': RETRY_TIMEOUT}
        try:
            _write_cache(team_id, payload)
        except Exception:
            db.session.rollback()
        trace.append({'step': 'pipeline failure', 'ok': False,
                      'reason': info['reason'],
                      'failure_kind': _FAILURE_LABELS.get(info['reason'], 'Error'),
                      'detail': info['message'],
                      'http_status': info['status'],
                      'bytes_read': info['bytes_read'],
                      'headers': info['headers'],
                      'retry_attempted': info['retry_attempted'],
                      'timeout': TIMEOUT, 'retry_timeout': RETRY_TIMEOUT,
                      'cache_preserved': bool(payload.get('events'))})
        log_event('integration.tymuj.debug.diagnostic_refresh', team_id=team_id, role='owner',
                  level='error', message=info['message'][:300],
                  meta={'ok': False, 'reason': info['reason'], 'status': info['status'],
                        'retry_attempted': info['retry_attempted']})
        return False, info['message'], trace
