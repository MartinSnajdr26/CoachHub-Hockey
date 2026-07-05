# -*- coding: utf-8 -*-
"""Saved training-session WhatsApp share — pure, testable message builder.

Builds a concise Czech share message (title + created date + drill count +
optional total duration + the existing session-detail link) and the standard
``wa.me`` share URL. No DB access, no new statuses, no secrets: it only formats
metadata the caller already has for the session.
"""
from urllib.parse import quote


def format_session_share_message(title, created_str, drill_count, total_duration_min, url):
    """Concise Czech share message.

    ``created_str`` is an already-formatted Czech date string ('' -> line
    omitted). ``total_duration_min`` is minutes; a falsy value omits the whole
    "Celková délka" line (no empty label). The link appears exactly once.
    """
    lines = [
        'Ahoj, posílám tréninkovou jednotku:',
        '',
        (title or 'Trénink').strip(),
        '',
        'Počet cvičení: %d' % (drill_count or 0),
    ]
    if total_duration_min:
        lines.append('Celková délka: %d min' % total_duration_min)
    if created_str:
        lines.append('Vytvořeno: %s' % created_str)
    lines += ['', 'Otevřít trénink:', url]
    return '\n'.join(lines)


def session_whatsapp_url(title, created_str, drill_count, total_duration_min, url):
    """Standard WhatsApp share link (no hardcoded recipient) for the message.

    On mobile ``wa.me`` opens the app; on desktop it opens WhatsApp Web. The
    coach picks the chat/group and sends manually — nothing is sent here.
    """
    message = format_session_share_message(title, created_str, drill_count, total_duration_min, url)
    return 'https://wa.me/?text=' + quote(message)
