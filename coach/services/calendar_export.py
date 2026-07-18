# -*- coding: utf-8 -*-
"""Calendar export helpers for the team .ics subscription feed.

No new DB columns. End time is DERIVED for export only, from the event `kind`:
  - training / trénink -> 75 minutes
  - match / zápas      -> 180 minutes
  - anything else       -> 90 minutes (fallback)

Timezone: coach-entered event day/time are naive LOCAL (Europe/Prague) wall-clock
values (see CLAUDE.md). We localize to Europe/Prague (DST-aware via zoneinfo) and
emit UTC (`...Z`) datetimes, which every calendar app accepts unambiguously. If
zoneinfo is unavailable we fall back to treating the wall-clock as UTC.

Pure module: no Flask imports, so it is trivially unit-testable.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

try:
    _PRAGUE = ZoneInfo('Europe/Prague')
except Exception:  # pragma: no cover - zoneinfo data present on this platform
    _PRAGUE = None

# Stable UID host so calendar clients update (not duplicate) an event when its
# time changes later. Must NOT depend on the request host.
UID_HOST = 'coachhubhockey.com'

# Derived durations (minutes) — export only, never stored.
DURATION_TRAINING = 75
DURATION_MATCH = 180
DURATION_FALLBACK = 90


def _get(event, name, default=None):
    """Read a field from either a dict or an ORM/object event."""
    if isinstance(event, dict):
        return event.get(name, default)
    return getattr(event, name, default)


def _norm_kind(kind):
    k = (kind or '').strip().lower()
    if k in ('training', 'trénink', 'trenink'):
        return 'training'
    if k in ('match', 'zápas', 'zapas'):
        return 'match'
    return 'other'


def duration_minutes(kind):
    k = _norm_kind(kind)
    if k == 'training':
        return DURATION_TRAINING
    if k == 'match':
        return DURATION_MATCH
    return DURATION_FALLBACK


def kind_label(kind):
    k = _norm_kind(kind)
    return {'training': 'Trénink', 'match': 'Zápas'}.get(k, 'Akce')


def summary_text(title, kind):
    title = (title or 'Akce').strip()
    k = _norm_kind(kind)
    if k in ('training', 'match'):
        return '%s: %s' % (kind_label(kind), title)
    return title


def build_description(kind, attendance_url):
    """Human-readable notes for the calendar entry, incl. the attendance link."""
    lines = ['Typ akce: %s' % kind_label(kind), '', 'Docházka:', attendance_url or '']
    return '\n'.join(lines).rstrip()


def _parse_hhmm(time_str):
    try:
        hh, mm = (time_str or '').strip().split(':')[:2]
        hh, mm = int(hh), int(mm)
        if 0 <= hh < 24 and 0 <= mm < 60:
            return hh, mm
    except Exception:
        pass
    return None


def _local_to_utc(day, hh, mm):
    naive = datetime(day.year, day.month, day.day, hh, mm)
    if _PRAGUE is not None:
        return naive.replace(tzinfo=_PRAGUE).astimezone(timezone.utc)
    return naive.replace(tzinfo=timezone.utc)


def start_end(day, time_str, kind):
    """Return (start, end, all_day).

    Timed event -> (aware UTC start, aware UTC end, False).
    No/blank time -> (day, day+1, True) for an all-day entry.
    """
    hm = _parse_hhmm(time_str)
    if hm is None:
        return day, day + timedelta(days=1), True
    start = _local_to_utc(day, hm[0], hm[1])
    end = start + timedelta(minutes=duration_minutes(kind))
    return start, end, False


def _fmt_utc(dt):
    return dt.strftime('%Y%m%dT%H%M%SZ')


def _fmt_date(d):
    return d.strftime('%Y%m%d')


def ics_escape(text):
    """Escape a text value per RFC 5545 (order matters: backslash first)."""
    if text is None:
        return ''
    return (str(text)
            .replace('\\', '\\\\')
            .replace(';', '\\;')
            .replace(',', '\\,')
            .replace('\r\n', '\n')
            .replace('\n', '\\n'))


def vevent_lines(event, attendance_url, stamp):
    """Return the VEVENT..END:VEVENT lines (incl. a 1-day VALARM) for one event."""
    title = _get(event, 'title')
    kind = _get(event, 'kind')
    day = _get(event, 'day')
    time_str = _get(event, 'time') or ''
    ev_id = _get(event, 'id') or 'x'
    start, end, all_day = start_end(day, time_str, kind)

    lines = [
        'BEGIN:VEVENT',
        'UID:coachhub-event-%s@%s' % (ev_id, UID_HOST),
        'DTSTAMP:%s' % stamp,
    ]
    if all_day:
        lines.append('DTSTART;VALUE=DATE:%s' % _fmt_date(start))
        lines.append('DTEND;VALUE=DATE:%s' % _fmt_date(end))
    else:
        lines.append('DTSTART:%s' % _fmt_utc(start))
        lines.append('DTEND:%s' % _fmt_utc(end))
    lines += [
        'SUMMARY:%s' % ics_escape(summary_text(title, kind)),
        'DESCRIPTION:%s' % ics_escape(build_description(kind, attendance_url)),
    ]
    if attendance_url:
        lines.append('URL:%s' % ics_escape(attendance_url))
    lines += [
        'BEGIN:VALARM',
        'TRIGGER:-P1D',
        'ACTION:DISPLAY',
        'DESCRIPTION:%s' % ics_escape('Zkontroluj docházku na zítřejší událost'),
        'END:VALARM',
        'END:VEVENT',
    ]
    return lines


def build_feed(events, attendance_url, cal_name='CoachHub', now_utc=None):
    """Return a full VCALENDAR string (CRLF) containing one VEVENT per event."""
    stamp = _fmt_utc(now_utc or datetime.now(timezone.utc))
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//CoachHub Hockey//Team Calendar//CS',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'X-WR-CALNAME:%s' % ics_escape(cal_name),
    ]
    for ev in events:
        lines += vevent_lines(ev, attendance_url, stamp)
    lines.append('END:VCALENDAR')
    return '\r\n'.join(lines) + '\r\n'
