"""Read-only attendance analytics for the coach matrix view.

Pure functions over already-loaded events/players/entries (no DB access here,
so callers load once and avoid N+1). Statuses: going|not_going|maybe|unknown
(missing entry = unknown / "no response").
"""
from datetime import date, timedelta

STATUSES = ('going', 'not_going', 'maybe', 'unknown')

# Shared date-range filter model used by BOTH the player page and the coach
# matrix, so the two stay consistent. Stable codes; labels live in templates.
RANGES = ('future', 'past', 'next30', 'all')
DEFAULT_RANGE = 'future'
# Backward-compat: map legacy/old query values onto the new codes.
RANGE_ALIASES = {
    'upcoming': 'future', 'season': 'all', 'month': 'all', 'today': 'next30',
    'last30': 'past', 'last90': 'past', 'custom': 'all',
}


def normalize_range(raw):
    """Map any (legacy) range value to a current code; unknown -> future."""
    r = (raw or '').strip()
    r = RANGE_ALIASES.get(r, r)
    return r if r in RANGES else DEFAULT_RANGE


def range_window(which, today=None):
    """(start, end) dates for a range code. Identical semantics on both pages."""
    today = today or date.today()
    if which == 'past':
        return today - timedelta(days=730), today - timedelta(days=1)
    if which == 'next30':
        return today, today + timedelta(days=30)
    if which == 'all':
        return today - timedelta(days=730), today + timedelta(days=730)
    return today, today + timedelta(days=365)            # future (default)
_CS_MONTHS = ['', 'led', 'úno', 'bře', 'dub', 'kvě', 'čvn',
              'čvc', 'srp', 'zář', 'říj', 'lis', 'pro']


def _color(pct, total):
    if not total:
        return 'none'
    if pct >= 80:
        return 'green'
    if pct >= 60:
        return 'yellow'
    return 'red'


def _pct(going, total):
    return round(going * 100 / total) if total else 0


def _initials(name):
    parts = [p for p in (name or '').split() if p]
    if not parts:
        return '?'
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _empty_counts():
    return {'going': 0, 'not_going': 0, 'maybe': 0, 'unknown': 0}


def build_matrix_view(events, players, entries, today=None):
    today = today or date.today()
    smap = {}                      # (player_id, event_key) -> status
    for e in entries:
        smap[(e.player_id, e.event_key)] = e.status or 'unknown'

    def status_of(pid, key):
        return smap.get((pid, key), 'unknown')

    n_players = len(players)
    # ---- events ----
    events_view = []
    for ev in events:
        is_match = (ev.get('kind') == 'match')
        c = _empty_counts()
        by_pos = {'G': _empty_counts(), 'D': _empty_counts(), 'F': _empty_counts()}
        names = {'going': [], 'not_going': [], 'maybe': [], 'unknown': []}
        for p in players:
            st = status_of(p.id, ev['key'])
            c[st] += 1
            pos = p.position if p.position in by_pos else 'F'
            by_pos[pos][st] += 1
            names[st].append(p.name)
        d = ev['day']
        pct = _pct(c['going'], n_players)
        events_view.append({
            'key': ev['key'], 'day': d.isoformat(),
            'day_label': '%d.%d.' % (d.day, d.month),
            'day_full': d.strftime('%d.%m.%Y'),
            'time': ev.get('time') or '', 'title': ev.get('title') or '',
            'kind': ev.get('kind') or 'training', 'source': ev.get('source') or 'local',
            'is_upcoming': d >= today,
            'summary': {**c, 'total': n_players, 'pct': pct, 'color': _color(pct, n_players)},
            'by_position': by_pos, 'names': names,
        })

    n_events = len(events)
    n_train = sum(1 for e in events if e.get('kind') != 'match')
    n_games = n_events - n_train
    # chronological event keys (for streaks / recent history)
    chron = sorted(events, key=lambda e: (e['day'], e.get('time') or ''))
    past_chron = [e for e in chron if e['day'] <= today]

    # ---- players ----
    players_view = []
    for p in players:
        c = _empty_counts()
        tr = {'going': 0, 'total': 0}
        gm = {'going': 0, 'total': 0}
        for ev in events:
            st = status_of(p.id, ev['key'])
            c[st] += 1
            if ev.get('kind') == 'match':
                gm['total'] += 1
                gm['going'] += (st == 'going')
            else:
                tr['total'] += 1
                tr['going'] += (st == 'going')
        # streak: consecutive 'going' from the most recent past event backwards
        streak = 0
        for ev in reversed(past_chron):
            if status_of(p.id, ev['key']) == 'going':
                streak += 1
            else:
                break
        # longest run of consecutive 'going' across past events
        longest = run = 0
        for ev in past_chron:
            if status_of(p.id, ev['key']) == 'going':
                run += 1
                longest = max(longest, run)
            else:
                run = 0
        recent = [{'key': ev['key'], 'status': status_of(p.id, ev['key']),
                   'day': ev['day'].isoformat(), 'kind': ev.get('kind') or 'training'}
                  for ev in past_chron[-10:]]
        pct = _pct(c['going'], n_events)
        players_view.append({
            'id': p.id, 'name': p.name, 'position': p.position or 'F',
            'initials': _initials(p.name),
            'summary': {**c, 'total': n_events, 'pct': pct, 'color': _color(pct, n_events)},
            'trainings': {**tr, 'pct': _pct(tr['going'], tr['total'])},
            'games': {**gm, 'pct': _pct(gm['going'], gm['total'])},
            'streak': streak, 'longest_streak': longest, 'recent': recent,
        })

    # ---- team KPIs ----
    rated = [pv for pv in players_view if pv['summary']['total'] > 0]
    avg_pct = round(sum(pv['summary']['pct'] for pv in rated) / len(rated)) if rated else 0
    best = max(rated, key=lambda pv: pv['summary']['pct'], default=None)
    worst = min(rated, key=lambda pv: pv['summary']['pct'], default=None)
    upcoming = [ev for ev in events_view if ev['is_upcoming']]
    up_total = sum(ev['summary']['total'] for ev in upcoming)
    up_going = sum(ev['summary']['going'] for ev in upcoming)
    no_response = sum(ev['summary']['unknown'] for ev in upcoming)
    team = {
        'avg_pct': avg_pct,
        'avg_color': _color(avg_pct, len(rated)),
        'upcoming_pct': _pct(up_going, up_total),
        'no_response_count': no_response,
        'best_player': {'name': best['name'], 'pct': best['summary']['pct']} if best else None,
        'worst_player': {'name': worst['name'], 'pct': worst['summary']['pct']} if worst else None,
        'total_events': n_events, 'total_trainings': n_train, 'total_games': n_games,
        'upcoming_count': len(upcoming),
        'players_total': n_players,
    }
    # compact status map for the client (non-unknown only)
    client_map = {}
    for (pid, key), st in smap.items():
        if st and st != 'unknown':
            client_map.setdefault(pid, {})[key] = st

    return {'events': events_view, 'players': players_view, 'team': team,
            'status_map': client_map}


def event_summary(players, entries_for_event):
    """Recompute one event's summary after an AJAX edit (small input)."""
    smap = {e.player_id: (e.status or 'unknown') for e in entries_for_event}
    c = _empty_counts()
    for p in players:
        c[smap.get(p.id, 'unknown')] += 1
    total = len(players)
    pct = _pct(c['going'], total)
    return {**c, 'total': total, 'pct': pct, 'color': _color(pct, total)}
