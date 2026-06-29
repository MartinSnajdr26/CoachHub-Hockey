"""League integration service: caching, rate-limited refresh, and a view model.

Responsibilities:
  * refresh()           — fetch + parse + store (manual or auto), rate limited.
  * maybe_auto_refresh()— refresh only if cache is stale (>= AUTO_REFRESH_HOURS).
  * get_view()          — read-only cached data for templates (NEVER fetches),
                          with team highlight + fuzzy-match suggestions + form.

Dashboard widgets call get_view() only -> external sites are not hit on load.
"""
from __future__ import annotations

import json
import unicodedata
import difflib
from datetime import datetime

from coach.extensions import db
from coach.models import LeagueIntegration, Team
from coach.services.logging import log_event
from coach.services.url_safety import validate_public_http_url
from . import get_connector
from .base import fetch_html_with_meta, parse_doc

AUTO_REFRESH_HOURS = 8           # auto-refresh cadence (within the 6–12h ask)
MIN_MANUAL_SECONDS = 0           # explicit refresh/test buttons may be retried
CACHE_SCHEMA = 3                 # bump when parsed shape changes -> old cache ignored
FORM_NEED = 5                    # last-N completed games for team form
MAX_FORM_ROUNDS = 10             # max previous rounds fetched per refresh (polite)


def get_integration(team_id):
    if not team_id:
        return None
    return LeagueIntegration.query.filter_by(team_id=team_id).first()


def _norm(s):
    s = unicodedata.normalize('NFKD', (s or ''))
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    return ' '.join(s.lower().split())


FORM_LABELS = {
    'cs': {'W': 'V', 'L': 'P', 'OW': 'VP', 'OL': 'PP'},
    'en': {'W': 'W', 'L': 'L', 'OW': 'OW', 'OL': 'OL'},
    'de': {'W': 'S', 'L': 'N', 'OW': 'VS', 'OL': 'VN'},
    'ja': {'W': '勝', 'L': '敗', 'OW': '延勝', 'OL': '延敗'},
}


def _result_code(r, team):
    """Internal hockey form code for one result (no Draw): W/L/OW/OL or None.
    `r` is a normalized result dict; `team` is the configured team name."""
    nf = _norm(team)
    if not nf:
        return None
    h, a = _norm(r.get('home_team')), _norm(r.get('away_team'))
    is_home = bool(h) and (nf == h or nf in h or h in nf)
    is_away = bool(a) and (nf == a or nf in a or a in nf)
    if is_home == is_away:           # neither side or ambiguous -> skip
        return None
    hs, as_ = r.get('home_score'), r.get('away_score')
    if hs is None or as_ is None or hs == as_:   # undecided / tie -> no W/L, skip (never 'D')
        return None
    win = (is_home and hs > as_) or (is_away and as_ > hs)
    ot = bool(r.get('ot'))
    return ('OW' if ot else 'W') if win else ('OL' if ot else 'L')


def _collect_form(conn, url, team, main_results, trace=None, html=None):
    """Return (codes[:5], partial). Uses the main page first, then politely
    walks previous rounds via the connector's AJAX navigation (vysledky).
    `html` is the freshly-fetched main page, used only to read the current round
    from its navigation. Only ever called from refresh() — never on dashboard
    render."""
    codes = []
    attempted = 0
    if not team:
        if trace is not None:
            trace.append({'step': 'form games collected', 'ok': False, 'detail': 'No team match name configured.', 'count': 0})
        return [], True
    for r in main_results:
        c = _result_code(r, team)
        if c:
            codes.append(c)
        if len(codes) >= FORM_NEED:
            if trace is not None:
                trace.append({'step': 'previous rounds attempted', 'ok': True, 'count': attempted})
                trace.append({'step': 'form games collected', 'ok': True, 'count': len(codes[:FORM_NEED]), 'codes': codes[:FORM_NEED]})
            return codes[:FORM_NEED], False
    # previous rounds (best-effort, polite, capped)
    try:
        import time
        cur = conn.detect_round(main_results, html=html) if hasattr(conn, 'detect_round') else None
        if cur and hasattr(conn, 'fetch_round'):
            for k in range(cur - 1, max(0, cur - MAX_FORM_ROUNDS) - 1, -1):
                attempted += 1
                for r in conn.fetch_round(url, k):
                    c = _result_code(r, team)
                    if c:
                        codes.append(c)
                if len(codes) >= FORM_NEED:
                    break
                time.sleep(0.4)   # be polite to the source
    except Exception:
        pass
    if trace is not None:
        trace.append({'step': 'previous rounds attempted', 'ok': True, 'count': attempted})
        trace.append({'step': 'form games collected', 'ok': bool(codes), 'count': len(codes[:FORM_NEED]), 'codes': codes[:FORM_NEED]})
    return codes[:FORM_NEED], (len(codes) < FORM_NEED)


def _match_team(li, standings):
    names = [s.get('team_name', '') for s in standings]
    target = (li.resolved_team or li.highlight_team or '').strip()
    result = {
        'target': target,
        'matched_team': None,
        'method': 'none',
        'confidence': 0.0,
        'suggestions': [],
        'needs_confirm': False,
    }
    if not target:
        return result
    nt = _norm(target)
    for s in standings:
        if _norm(s.get('team_name')) == nt:
            result.update({'matched_team': s['team_name'], 'method': 'exact', 'confidence': 1.0})
            return result
    for s in standings:
        sn = _norm(s.get('team_name'))
        if nt and sn and (nt in sn or sn in nt):
            result.update({'matched_team': s['team_name'], 'method': 'contains', 'confidence': 0.85})
            return result
    if li.resolved_team in names:
        result.update({'matched_team': li.resolved_team, 'method': 'confirmed', 'confidence': 1.0})
        return result
    if not li.resolved_team:
        close = difflib.get_close_matches(target, names, n=3, cutoff=0.6)
        result['suggestions'] = close
        result['needs_confirm'] = bool(close)
        if close:
            ratio = difflib.SequenceMatcher(None, _norm(target), _norm(close[0])).ratio()
            result.update({'matched_team': close[0], 'method': 'fuzzy', 'confidence': round(ratio, 3)})
    return result


def _cache_validation(data):
    if not data:
        return False, 'cache is empty'
    if data.get('_schema') != CACHE_SCHEMA:
        return False, 'schema %s != %s' % (data.get('_schema'), CACHE_SCHEMA)
    standings = data.get('standings', []) or []
    if any((s.get('points', 0) or 0) > 999 or (s.get('played', 0) or 0) > 200 for s in standings):
        return False, 'standings sanity guard failed'
    if not standings:
        return False, 'no standings rows'
    return True, 'ok'


def _competition_id(url):
    try:
        import urllib.parse
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url or '').query)
        return (q.get('id_soutez') or q.get('competition_id') or [''])[0]
    except Exception:
        return ''


def refresh(team_id, manual=False):
    """Fetch + parse + store. Returns (ok: bool, message: str).
    On failure keeps the last successful cache and records last_error."""
    li = get_integration(team_id)
    if not li or not (li.source_url or '').strip():
        return (False, 'Není nastavena URL soutěže.')
    now = datetime.utcnow()
    if manual and li.last_attempt and (now - li.last_attempt).total_seconds() < MIN_MANUAL_SECONDS:
        return (False, 'Příliš mnoho pokusů. Zkus to znovu za chvíli.')
    li.last_attempt = now
    db.session.commit()
    try:
        conn = get_connector(li.source_url)
        html, fetch_meta = fetch_html_with_meta(li.source_url)
        data_obj = conn.parse(parse_doc(html), li.source_url)
        data_obj.info.source_url = li.source_url
        data_obj.info.last_updated = now.isoformat()
        data = data_obj.to_dict()
        team_names = [s.get('team_name') for s in data.get('standings', []) if s.get('team_name')]
        current_app_meta = {
            'url': li.source_url,
            'download_bytes': fetch_meta.get('bytes'),
            'encoding': fetch_meta.get('encoding'),
            'connector': conn.name,
            'standings_rows': len(data.get('standings') or []),
            'results_rows': len(data.get('results') or []),
            'team_names': team_names[:20],
            'selected_team': li.resolved_team or li.highlight_team,
        }
        log_event('integration.league.debug.parse', team_id=team_id, role='coach', level='info',
                  message='League parser output', meta=current_app_meta)
        if not data.get('standings'):
            raise ValueError('Parser nenašel ligovou tabulku.')
        # team form from last completed games (walks previous rounds politely)
        team = li.resolved_team or li.highlight_team or ''
        form, partial = _collect_form(conn, li.source_url, team, data.get('results', []), html=html)
        data['team_form'] = form
        data['form_partial'] = partial
        data['_schema'] = CACHE_SCHEMA
        li.connector = conn.name
        li.data_json = json.dumps(data, ensure_ascii=False)
        li.last_updated = now
        li.last_error = None
        db.session.commit()
        log_event('integration.league.debug.cache_write', team_id=team_id, role='coach', level='info',
                  message='League cache written',
                  meta={'schema': data.get('_schema'), 'json_bytes': len(li.data_json or ''),
                        'standings_rows': len(data['standings']), 'results_rows': len(data['results']),
                        'team_form': data.get('team_form')})
        log_event('integration.league.success', team_id=team_id, role='coach', level='info',
                  message='League refresh succeeded',
                  meta={'teams': len(data['standings']), 'results': len(data['results']), 'connector': conn.name})
        return (True, 'Data načtena: %d týmů v tabulce, %d výsledků.'
                % (len(data['standings']), len(data['results'])))
    except Exception as e:  # network/parse errors -> keep last good cache
        db.session.rollback()
        li = get_integration(team_id)
        if li:
            li.last_error = ('%s' % e)[:400]
            db.session.commit()
        log_event('integration.league.failure', team_id=team_id, role='coach', level='error',
                  message=str(e), meta={'connector': li.connector if li else None, 'has_cache': bool(li and li.data_json)})
        return (False, 'Načtení se nezdařilo: %s' % (('%s' % e)[:200]))


def maybe_auto_refresh(team_id):
    """Refresh only when enabled and the cache is stale, and not hammered.
    Safe to call on a page load (Settings); a fetch happens at most ~every
    AUTO_REFRESH_HOURS. Never called from the dashboard render path."""
    li = get_integration(team_id)
    if not li or not li.enabled or not (li.source_url or '').strip():
        return
    now = datetime.utcnow()
    stale = (li.last_updated is None) or ((now - li.last_updated).total_seconds() > AUTO_REFRESH_HOURS * 3600)
    # Also re-parse if the cache was written by an older parser (schema bump).
    schema_old = False
    if li.data_json:
        try:
            schema_old = json.loads(li.data_json).get('_schema') != CACHE_SCHEMA
        except Exception:
            schema_old = True
    backoff = li.last_attempt and (now - li.last_attempt).total_seconds() < (AUTO_REFRESH_HOURS * 3600 / 4)
    if (stale or schema_old) and not backoff:
        refresh(team_id, manual=False)


def get_view(team_id):
    """Read cached data for templates. No external fetch. Returns None when the
    integration is missing/disabled (dashboard simply renders nothing)."""
    li = get_integration(team_id)
    if not li or not li.enabled:
        return None
    view = {
        'enabled': True,
        'error': li.last_error,
        'updated': li.last_updated,
        'connector': li.connector,
        'source_url': li.source_url,
        'info': None,
        'standings': [],
        'results': [],
        'team_row': None,
        'form': [],
        'form_cards': [],
        'form_labels': FORM_LABELS,
        'form_partial': False,
        'stale_schema': False,
        'suggestions': [],
        'needs_confirm': False,
        'highlight': li.resolved_team or li.highlight_team,
    }
    if not li.data_json:
        return view
    try:
        data = json.loads(li.data_json)
    except Exception:
        return view
    # NOTE: get_view() is a read-only render path (dashboard / settings GET) and
    # MUST NOT write to the DB. The previous 'cache_load' audit log_event here
    # inserted+committed an AuditEvent on every page view (unbounded growth +
    # a commit per render); removed. Refresh/test/diagnostic paths still log.
    standings = data.get('standings', []) or []
    valid, _reason = _cache_validation(data)
    if not valid:
        view['stale_schema'] = True
        return view
    results = data.get('results', []) or []
    view['info'] = data.get('info')

    match = _match_team(li, standings)
    final = match['matched_team']
    view['suggestions'] = match['suggestions']
    view['needs_confirm'] = match['needs_confirm']

    for s in standings:
        s['is_team'] = bool(final) and s.get('team_name') == final
    view['standings'] = standings
    view['results'] = results
    view['team_row'] = next((s for s in standings if s.get('is_team')), None)

    # Form: prefer the codes collected at refresh time (may span previous rounds);
    # otherwise derive W/L/OW/OL from cached results (never 'D').
    cached_form = data.get('team_form')
    if cached_form:
        view['form'] = cached_form[:FORM_NEED]
        view['form_partial'] = bool(data.get('form_partial'))
    elif final:
        codes = []
        for r in results:
            c = _result_code(r, final)
            if c:
                codes.append(c)
        view['form'] = codes[:FORM_NEED]
        view['form_partial'] = len(codes) < FORM_NEED
    labels = FORM_LABELS['cs']
    view['form_cards'] = [{'code': c, 'label': labels.get(c, c)} for c in view['form']]
    return view


def league_debug_rows():
    rows = []
    integrations = (LeagueIntegration.query
                    .order_by(LeagueIntegration.team_id.asc(), LeagueIntegration.id.asc())
                    .all())
    for li in integrations:
        rows.append(league_debug_summary(li))
    return rows


def league_debug_summary(li):
    team = Team.query.get(li.team_id) if li and li.team_id else None
    data = {}
    parse_error = None
    if li and li.data_json:
        try:
            data = json.loads(li.data_json)
        except Exception as exc:
            parse_error = str(exc)
            data = {}
    standings = data.get('standings', []) or []
    results = data.get('results', []) or []
    form = data.get('team_form', []) or []
    info = data.get('info') or {}
    match = _match_team(li, standings) if li else {}
    valid, validation = _cache_validation(data) if data else (False, 'cache is empty')
    cache_age = None
    if li and li.last_updated:
        cache_age = datetime.utcnow() - li.last_updated
    return {
        'team': team,
        'integration': li,
        'provider': li.connector or (get_connector(li.source_url).name if li and li.source_url else ''),
        'competition_id': _competition_id(li.source_url if li else ''),
        'cache_schema': data.get('_schema') if data else None,
        'cache_age': cache_age,
        'standings_count': len(standings),
        'results_count': len(results),
        'form_count': len(form),
        'competition_name': info.get('competition_name'),
        'season': info.get('season'),
        'detected_teams': [s.get('team_name') for s in standings if s.get('team_name')],
        'matched_team': match.get('matched_team'),
        'matched_method': match.get('method'),
        'matched_confidence': match.get('confidence'),
        'stale_warning': not valid,
        'cache_validation': validation,
        'parse_error': parse_error,
        'standings_json': standings,
        'results_json': results,
        'form_json': form,
        'summary_json': {
            'schema': data.get('_schema') if data else None,
            'valid': valid,
            'validation': validation,
            'standings_count': len(standings),
            'results_count': len(results),
            'form_count': len(form),
            'matched_team': match.get('matched_team'),
            'matched_method': match.get('method'),
            'matched_confidence': match.get('confidence'),
        },
    }


def diagnostic_refresh(team_id):
    li = get_integration(team_id)
    trace = []
    if not li:
        trace.append({'step': 'integration config', 'ok': False, 'detail': 'No LeagueIntegration row.'})
        return False, 'League integration is not configured.', trace
    now = datetime.utcnow()
    url = (li.source_url or '').strip()
    conn = get_connector(url)
    trace.append({'step': 'provider selected', 'ok': True, 'value': conn.name})
    trace.append({'step': 'URL generated', 'ok': bool(url), 'value': url})
    ok_url, url_msg = validate_public_http_url(url)
    trace.append({'step': 'URL safety check', 'ok': ok_url, 'detail': url_msg or 'ok'})
    if not ok_url:
        li.last_attempt = now
        li.last_error = url_msg[:400]
        db.session.commit()
        return False, url_msg, trace
    try:
        li.last_attempt = now
        db.session.commit()
        html, fetch_meta = fetch_html_with_meta(url)
        trace.append({'step': 'HTTP status', 'ok': True, 'value': fetch_meta.get('http_status')})
        trace.append({'step': 'download size', 'ok': True, 'value': fetch_meta.get('bytes')})
        trace.append({'step': 'detected encoding', 'ok': True, 'value': fetch_meta.get('encoding')})
        trace.append({'step': 'parser selected', 'ok': True, 'value': conn.name})
        data_obj = conn.parse(parse_doc(html), url)
        data_obj.info.source_url = url
        data_obj.info.last_updated = now.isoformat()
        data = data_obj.to_dict()
        trace.append({'step': 'standings rows parsed', 'ok': bool(data.get('standings')), 'count': len(data.get('standings') or [])})
        trace.append({'step': 'results parsed', 'ok': True, 'count': len(data.get('results') or [])})
        if not data.get('standings'):
            raise ValueError('Parser nenašel ligovou tabulku.')
        match = _match_team(li, data.get('standings') or [])
        trace.append({'step': 'team matching result', 'ok': bool(match.get('matched_team')), **match})
        form_team = match.get('matched_team') or li.resolved_team or li.highlight_team or ''
        form, partial = _collect_form(conn, url, form_team, data.get('results', []), trace=trace, html=html)
        data['team_form'] = form
        data['form_partial'] = partial
        data['_schema'] = CACHE_SCHEMA
        valid, validation = _cache_validation(data)
        trace.append({'step': 'cache validation result', 'ok': valid, 'detail': validation})
        if not valid:
            raise ValueError(validation)
        li.connector = conn.name
        li.data_json = json.dumps(data, ensure_ascii=False)
        li.last_updated = now
        li.last_error = None
        db.session.commit()
        trace.append({'step': 'cache write result', 'ok': True, 'schema': CACHE_SCHEMA, 'json_bytes': len(li.data_json or '')})
        view = get_view(team_id)
        trace.append({'step': 'dashboard view model result', 'ok': bool(view and view.get('standings')),
                      'standings_rows': len(view.get('standings') or []) if view else 0,
                      'results_rows': len(view.get('results') or []) if view else 0,
                      'team_row': (view.get('team_row') or {}).get('team_name') if view else None,
                      'form_games': len(view.get('form') or []) if view else 0,
                      'stale_schema': bool(view and view.get('stale_schema'))})
        log_event('integration.league.debug.diagnostic_refresh', team_id=team_id, role='owner', level='info',
                  message='Owner diagnostic refresh completed',
                  meta={'ok': True, 'steps': len(trace), 'standings': len(data.get('standings') or []),
                        'results': len(data.get('results') or [])})
        return True, 'Diagnostic refresh completed.', trace
    except Exception as exc:
        db.session.rollback()
        li = get_integration(team_id)
        if li:
            li.last_error = str(exc)[:400]
            db.session.commit()
        trace.append({'step': 'pipeline failure', 'ok': False, 'detail': str(exc)})
        log_event('integration.league.debug.diagnostic_refresh', team_id=team_id, role='owner', level='error',
                  message=str(exc), meta={'ok': False, 'steps': len(trace)})
        return False, str(exc), trace


def save_config(team_id, enabled, source_url, highlight_team):
    """Upsert the integration config (does not fetch)."""
    li = get_integration(team_id)
    if not li:
        li = LeagueIntegration(team_id=team_id)
        db.session.add(li)
    new_url = (source_url or '').strip()
    if new_url != (li.source_url or ''):
        # URL changed -> stale cache + reset resolved team
        li.data_json = None
        li.last_updated = None
        li.last_error = None
        li.resolved_team = None
    li.enabled = bool(enabled)
    li.source_url = new_url[:500]
    li.highlight_team = (highlight_team or '').strip()[:120] or None
    li.connector = get_connector(new_url).name if new_url else None
    db.session.commit()
    return li


def confirm_team(team_id, team_name):
    li = get_integration(team_id)
    if li:
        li.resolved_team = (team_name or '').strip()[:120] or None
        db.session.commit()
