"""Recurring calendar event generation (Calendar 2.0).

Pure date math — no DB. Generates the list of occurrence dates for a series
from a start date + rule, bounded by an end condition (until OR count) and a
hard safety cap. Kept deliberately simple (no full RRULE engine).
"""
from datetime import date, timedelta

MAX_OCCURRENCES = 100
FREQUENCIES = ('daily', 'weekly', 'biweekly', 'monthly')
WEEKDAYS = ('MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU')   # index == date.weekday()
_WD_INDEX = {w: i for i, w in enumerate(WEEKDAYS)}


def build_rule(freq, weekdays):
    """Compact rule string stored per occurrence, e.g. 'weekly:MO,WE'."""
    if freq in ('weekly', 'biweekly') and weekdays:
        return '%s:%s' % (freq, ','.join(weekdays))
    return freq


def generate_dates(start, freq, weekdays=None, until=None, count=None, cap=MAX_OCCURRENCES):
    """Return (dates, capped).

    start: date of the first occurrence (anchor).
    freq:  daily | weekly | biweekly | monthly.
    weekdays: list of 'MO'..'SU' (weekly/biweekly); defaults to start's weekday.
    until: inclusive end date (or None).
    count: max number of occurrences (or None). One of until/count must be given.
    cap:   hard safety limit; if hit, capped=True.
    """
    if freq not in FREQUENCIES:
        return [], False
    if until is None and not count:
        return [], False
    limit = min(cap, count) if count else cap
    out = []
    capped = False

    def add(d):
        nonlocal capped
        if until and d > until:
            return False
        if len(out) >= limit:
            capped = (count is None) or (count > cap)
            return False
        out.append(d)
        return True

    if freq == 'daily':
        d = start
        while True:
            if not add(d):
                break
            d = d + timedelta(days=1)

    elif freq in ('weekly', 'biweekly'):
        step_weeks = 2 if freq == 'biweekly' else 1
        wds = sorted({_WD_INDEX[w] for w in (weekdays or []) if w in _WD_INDEX})
        if not wds:
            wds = [start.weekday()]
        # anchor to the Monday of the start's week
        week_monday = start - timedelta(days=start.weekday())
        stop = False
        guard = 0
        while not stop and guard < 520:        # ~10 years of weeks, safety
            guard += 1
            for wd in wds:
                d = week_monday + timedelta(days=wd)
                if d < start:
                    continue
                if until and d > until:
                    stop = True
                    break
                if not add(d):
                    stop = True
                    break
            week_monday = week_monday + timedelta(weeks=step_weeks)

    elif freq == 'monthly':
        day_of_month = start.day
        y, m = start.year, start.month
        guard = 0
        while guard < cap + 12:
            guard += 1
            try:
                d = date(y, m, day_of_month)
            except ValueError:
                d = None                       # e.g. 31st in a short month -> skip
            if d is not None:
                if until and d > until:
                    break
                if not add(d):
                    break
            m += 1
            if m > 12:
                m = 1
                y += 1

    return out, capped
