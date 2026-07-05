# -*- coding: utf-8 -*-
"""WhatsApp attendance reminder — pure, testable helpers.

The "unanswered" definition mirrors ``attendance_stats.build_matrix_view`` /
``status_of``: a player is unanswered when their status for the event is
``unknown`` OR there is no attendance record at all. The explicit responses
``going`` (Ano), ``not_going`` (Ne) and ``maybe`` (Možná) are treated as answered
and excluded. No new attendance statuses are introduced, no DB writes happen
here, and no phone numbers / group identifiers are stored.
"""
from urllib.parse import quote

# Statuses that count as an EXPLICIT response and are therefore EXCLUDED from a
# reminder. Everything else (``unknown`` / missing record / empty) is included.
ANSWERED = frozenset({'going', 'not_going', 'maybe'})


def unanswered_player_names(players, entries, event_key):
    """Return the names of players who have not answered for ``event_key``.

    ``players`` must be the active, already-ordered team player list the
    attendance screen uses (ordering is preserved). ``entries`` is the team's
    ``AttendanceEntry`` rows. A missing (player, event) record counts as
    ``unknown`` → included. Each player appears at most once.
    """
    status_by = {(e.player_id, e.event_key): (e.status or 'unknown') for e in entries}
    names = []
    for p in players:
        status = status_by.get((p.id, event_key), 'unknown')
        if status not in ANSWERED:
            names.append(p.name)
    return names


def format_reminder_message(event_title, event_day, event_time, names, player_url):
    """Build the concise Czech reminder message.

    ``event_day`` is a ``datetime.date``; ``event_time`` a string (``''`` / None
    is omitted cleanly). No location is included. The player list is rendered in
    the given order, one per line.
    """
    date_cs = '%d. %d. %d' % (event_day.day, event_day.month, event_day.year)
    time_txt = (event_time or '').strip()
    when = ('%s %s' % (date_cs, time_txt)) if time_txt else date_cs
    lines = [
        'Ahoj, prosím o doplnění docházky na:',
        '',
        (event_title or 'Akce').strip(),
        when,
        '',
        'Docházku zatím nemají vyplněnou:',
    ]
    lines.extend('- ' + n for n in names)
    lines.extend(['', 'Docházku doplňte zde:', player_url, '', 'Děkuji.'])
    return '\n'.join(lines)


def whatsapp_share_url(message):
    """Standard WhatsApp share link with NO hardcoded recipient.

    On mobile ``wa.me`` opens the app; on desktop it opens WhatsApp Web. The
    coach picks the group/chat and sends manually — nothing is sent here.
    """
    return 'https://wa.me/?text=' + quote(message)
