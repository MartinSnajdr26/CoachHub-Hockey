import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, abort
from coach.auth_utils import team_login_required, get_team_id, coach_required, get_team_role
from coach.extensions import db
from datetime import date, datetime, timedelta
import calendar as calmod
from coach.models import TrainingEvent, AuditEvent, Player, AttendanceEntry, LineupSession, Drill
from coach.services import tymuj as tymuj_svc
from coach.services import calendar_export
from coach.services import calendar_feed

bp = Blueprint('calendar', __name__)

# Team calendar feed spans today .. +6 months.
_FEED_HORIZON_DAYS = 183


def _prod_external(endpoint, **values):
    """Absolute URL; https forced in production, host from the request otherwise."""
    if (os.getenv('APP_ENV') or '').strip().lower() == 'production':
        return url_for(endpoint, _external=True, _scheme='https', **values)
    return url_for(endpoint, _external=True, **values)


def team_feed_url_for(token):
    """Absolute HTTPS-in-prod .ics feed URL for a token (used by the UI)."""
    return _prod_external('calendar.team_feed', token=token)


@bp.route('/calendar/team/<token>.ics', endpoint='team_feed')
def team_feed(token):
    """Public, read-only team calendar subscription feed.

    No login: the URL token IS the bearer secret. An invalid/rotated token
    returns a plain 404 and never reveals whether a team exists. Only the
    token's own team's future events are included — no cross-team leakage.
    """
    tid = calendar_feed.team_for_token(token)
    if not tid:
        abort(404)
    today = date.today()
    events = (TrainingEvent.query
              .filter(TrainingEvent.team_id == tid,
                      TrainingEvent.day >= today,
                      TrainingEvent.day <= today + timedelta(days=_FEED_HORIZON_DAYS))
              .order_by(TrainingEvent.day.asc(), TrainingEvent.time.asc())
              .all())
    # Feed is not session-authenticated -> use the general player attendance page.
    attendance_url = _prod_external('attendance.attendance')
    ics = calendar_export.build_feed(events, attendance_url, cal_name='CoachHub')
    resp = Response(ics)
    resp.headers['Content-Type'] = 'text/calendar; charset=utf-8'
    resp.headers['Content-Disposition'] = 'inline; filename="coachhub-team.ics"'
    return resp


@bp.route('/app', endpoint='home')
@team_login_required
def home():
    try:
        y = int(request.args.get('year', ''))
        m = int(request.args.get('month', ''))
    except Exception:
        y = 0; m = 0
    today = date.today()
    if not (1 <= m <= 12) or y < 1900:
        y, m = today.year, today.month
    cal = calmod.Calendar(firstweekday=0)
    weeks = [list(wk) for wk in cal.monthdatescalendar(y, m)]
    first_day = date(y, m, 1)
    next_first = date(y+1, 1, 1) if m == 12 else date(y, m+1, 1)
    last_day = next_first - timedelta(days=1)
    events_by_day = {}
    tid = get_team_id()
    if tid:
        evs = (TrainingEvent.query
               .filter(TrainingEvent.team_id == tid,
                       TrainingEvent.day >= first_day,
                       TrainingEvent.day <= last_day)
               .order_by(TrainingEvent.day.asc(), TrainingEvent.time.asc())
               .all())
        for e in evs:
            key = e.day.isoformat()
            events_by_day.setdefault(key, []).append(e)
        for item in tymuj_svc.get_cached_events(tid, first_day, last_day):
            key = item['day'].isoformat()
            events_by_day.setdefault(key, []).append(item)
    if m == 1:
        prev_y, prev_m = y-1, 12
    else:
        prev_y, prev_m = y, m-1
    if m == 12:
        next_y, next_m = y+1, 1
    else:
        next_y, next_m = y, m+1
    cs_months = ['-', "leden","únor","březen","duben","květen","červen",
                 "červenec","srpen","září","říjen","listopad","prosinec"]
    month_title = f"{cs_months[m]} {y}"
    today_label = f"{today.day}. {cs_months[today.month]} {today.year}"
    # Load team messages (message board) without DB migration, using AuditEvent
    msgs = []
    view_messages = []
    month_num = m  # keep month safe from shadowing
    if tid:
        try:
            msgs = (AuditEvent.query
                    .filter(AuditEvent.team_id == tid, AuditEvent.event == 'message')
                    .order_by(AuditEvent.created_at.desc())
                    .limit(50)
                    .all())
            from json import loads
            for msg in msgs:
                try:
                    payload = loads(msg.meta or '{}') if msg.meta else {}
                except Exception:
                    payload = {}
                view_messages.append({
                    'id': msg.id,
                    'text': (payload.get('text') or '').strip(),
                    'role': (payload.get('role') or msg.role or 'player'),
                    'pinned': bool(payload.get('pinned')),
                    'created_at': msg.created_at,
                })
            # Pinned first, then by time desc
            view_messages.sort(key=lambda x: (not x['pinned'], x['created_at']), reverse=True)
        except Exception:
            view_messages = []
    # Determine role explicitly for template (robust against any transient context issues)
    from coach.auth_utils import get_team_role
    is_coach_home = (get_team_role() == 'coach')
    # sort events in each day by time and source
    for key, items in events_by_day.items():
        items.sort(key=lambda ev: ((ev.get('time') or '') if isinstance(ev, dict) else (ev.time or ''), ev.get('source') if isinstance(ev, dict) else getattr(ev, 'kind', '')))

    # ---- Dashboard widgets: read-only derived data (never break the page) ----
    cs_wd = ['Po', 'Út', 'St', 'Čt', 'Pá', 'So', 'Ne']

    def _fmt_day(d):
        try:
            return f"{cs_wd[d.weekday()]} {d.day}. {cs_months[d.month]}"
        except Exception:
            return d.isoformat() if d else ''

    dash = {
        'players_total': 0,
        'next_practice': None,
        'next_game': None,
        'upcoming': [],
        'attendance': None,
        'recent_messages_7d': 0,
        'latest_lineup': None,
        'recent_drills': [],
        'recent_activity': [],
        'first_name': None,
    }
    try:
        if tid:
            horizon = today + timedelta(days=120)
            upcoming = _collect_events_for_team(tid, today, horizon)
            for e in upcoming:
                e['label'] = _fmt_day(e['day'])
                e['is_game'] = (e.get('kind') == 'match')
                e['is_today'] = (e['day'] == today)
            dash['upcoming'] = upcoming[:8]
            dash['next_game'] = next((e for e in upcoming if e['is_game']), None)
            dash['next_practice'] = next((e for e in upcoming if not e['is_game']), None)

            players = Player.query.filter_by(team_id=tid).order_by(Player.name.asc()).all()
            dash['players_total'] = len(players)

            next_event = upcoming[0] if upcoming else None
            if next_event and players:
                statuses = {a.player_id: a.status for a in AttendanceEntry.query
                            .filter_by(team_id=tid, event_key=next_event['key']).all()}
                going = [p for p in players if statuses.get(p.id) == 'going']
                not_going = [p for p in players if statuses.get(p.id) == 'not_going']
                pending = [p for p in players if statuses.get(p.id, 'unknown') == 'unknown']
                total = len(players)
                dash['attendance'] = {
                    'event': next_event,
                    'going': len(going),
                    'not_going': len(not_going),
                    'pending': len(pending),
                    'total': total,
                    'pct': round(len(going) * 100 / total) if total else 0,
                    'missing_names': [p.name for p in not_going][:8],
                    'pending_names': [p.name for p in pending][:8],
                }

            wk_ago = datetime.utcnow() - timedelta(days=7)
            dash['recent_messages_7d'] = sum(1 for mm in view_messages
                                             if mm.get('created_at') and mm['created_at'] >= wk_ago)
            dash['latest_lineup'] = (LineupSession.query.filter_by(team_id=tid)
                                     .order_by(LineupSession.created_at.desc()).first())
            dash['recent_drills'] = (Drill.query.filter_by(team_id=tid)
                                     .order_by(Drill.id.desc()).limit(5).all())
            dash['recent_activity'] = (AuditEvent.query.filter_by(team_id=tid)
                                       .order_by(AuditEvent.created_at.desc()).limit(7).all())
    except Exception as e:
        try:
            from flask import current_app
            current_app.logger.warning('dashboard widgets failed: %s', e)
        except Exception:
            pass

    today_weekday = cs_wd[today.weekday()]

    # League widgets — cached data only (NEVER fetches external pages on load)
    league = None
    try:
        from coach.services.league import service as league_svc
        league = league_svc.get_view(tid)
    except Exception:
        league = None

    # Team calendar subscription: lazily create/reuse this team's feed token so
    # the Dashboard can show the "Připojit týmový kalendář" link. Never break the
    # page if the feed table is missing (e.g. migration not yet applied).
    team_feed_url = None
    try:
        if tid:
            tok = calendar_feed.get_or_create_active_token(tid)
            if tok:
                team_feed_url = team_feed_url_for(tok.token)
    except Exception:
        db.session.rollback()
        team_feed_url = None

    return render_template('home.html',
                           league=league,
                           cal_year=y, cal_month=month_num, month_title=month_title, weeks=weeks,
                           events_by_day=events_by_day,
                           prev_year=prev_y, prev_month=prev_m,
                           next_year=next_y, next_month=next_m,
                           today_label=today_label,
                           today_weekday=today_weekday,
                           today_iso=today.isoformat(),
                           team_messages=view_messages,
                           dash=dash,
                           team_feed_url=team_feed_url,
                           is_coach_home=is_coach_home)


def _collect_events_for_team(tid: int, start_date: date, end_date: date) -> list[dict]:
    events = []
    if not tid:
        return events
    local_events = (TrainingEvent.query
                    .filter(TrainingEvent.team_id == tid,
                            TrainingEvent.day >= start_date,
                            TrainingEvent.day <= end_date)
                    .order_by(TrainingEvent.day.asc(), TrainingEvent.time.asc())
                    .all())
    for ev in local_events:
        events.append({
            'id': ev.id,
            'key': f"local:{ev.id}",
            'day': ev.day,
            'time': ev.time or '',
            'title': ev.title or 'Trénink',
            'kind': ev.kind or 'training',
            'source': 'local',
            # Additive, read-only: lets the mobile Dashboard event manager show the
            # recurrence scope selector (one/future/series). Desktop calendar uses a
            # separate data path (events_by_day) and never reads this.
            'series_id': ev.series_id,
        })
    for item in tymuj_svc.get_cached_events(tid, start_date, end_date):
        key = tymuj_svc.make_event_key(item['title'], item['day'], item.get('time') or '', item.get('kind') or 'tymuj', 'tymuj')
        events.append({
            'id': None,
            'key': key,
            'day': item['day'],
            'time': item.get('time') or '',
            'title': item['title'],
            'kind': item.get('kind') or 'training',
            'source': 'tymuj',
        })
    events.sort(key=lambda ev: (ev['day'], ev['time'], ev['title']))
    return events


@bp.route('/dochazka', methods=['GET', 'POST'], endpoint='dochazka')
@team_login_required
def dochazka():
    tid = get_team_id()
    if not tid:
        return redirect(url_for('team_auth'))
    if request.method == 'POST':
        resp = coach_required(lambda: None)()
        if resp is not None:
            return resp
        start_date = date.today() - timedelta(days=45)
        end_date = date.today() + timedelta(days=180)
        event_lookup = {event['key']: event for event in _collect_events_for_team(tid, start_date, end_date)}
        valid_player_ids = {p.id for p in Player.query.filter_by(team_id=tid).all()}
        for key, value in request.form.items():
            if not key.startswith('status_'):
                continue
            _, event_key, player_id_s = key.split('_', 2)
            try:
                player_id = int(player_id_s)
            except Exception:
                continue
            if player_id not in valid_player_ids:
                continue
            status = (value or 'unknown').strip().lower()
            if status not in {'going', 'not_going', 'maybe', 'unknown'}:
                status = 'unknown'
            event_meta = event_lookup.get(event_key, {})
            entry = AttendanceEntry.query.filter_by(team_id=tid, player_id=player_id, event_key=event_key).first()
            if entry:
                entry.status = status
                entry.source = 'coachhub_coach'
                entry.updated_by_role = 'coach'
                entry.event_title = (event_meta.get('title') or entry.event_title or '').strip()[:200]
                entry.event_day = event_meta.get('day') or entry.event_day
                entry.event_time = (event_meta.get('time') or entry.event_time or '')[:10]
                entry.event_kind = (event_meta.get('kind') or entry.event_kind or 'training')[:20]
                entry.event_source = (event_meta.get('source') or entry.event_source or 'local')[:20]
            else:
                entry = AttendanceEntry(
                    team_id=tid,
                    player_id=player_id,
                    event_key=event_key,
                    status=status,
                    source='coachhub_coach',
                    updated_by_role='coach',
                    event_title=(event_meta.get('title') or '')[:200],
                    event_day=event_meta.get('day') or date.today(),
                    event_time=(event_meta.get('time') or '')[:10],
                    event_kind=(event_meta.get('kind') or 'training')[:20],
                    event_source=(event_meta.get('source') or 'local')[:20],
                )
                db.session.add(entry)
            db.session.flush()
        db.session.commit()
        flash('Docházka byla aktualizována.', 'success')
        return redirect(url_for('dochazka'))

    # ---- filters: SAME date-range model as the player page (future/past/
    #      next30/all, default future). Range is remembered client-side in
    #      localStorage 'att_range' (mirrors the player page); etype is a
    #      matrix-only filter kept in session. Old range values are mapped. ----
    from flask import session as _session
    from coach.services import attendance_stats as stats
    saved = _session.get('att_filters') or {}
    rng = stats.normalize_range(request.args.get('range'))   # default future, maps legacy values
    etype = (request.args.get('etype') or saved.get('etype') or 'all').strip()
    if etype not in ('all', 'training', 'match', 'camp', 'other'):
        etype = 'all'
    _session['att_filters'] = {'etype': etype}

    today = date.today()
    start_date, end_date = stats.range_window(rng, today)
    events = _collect_events_for_team(tid, start_date, end_date)
    if etype != 'all':
        events = [e for e in events if (e.get('kind') or 'training') == etype]

    players = Player.query.filter_by(team_id=tid).order_by(Player.name.asc()).all()
    entries = AttendanceEntry.query.filter_by(team_id=tid).all()
    view = stats.build_matrix_view(events, players, entries, today=today)

    tymuj_status = tymuj_svc.get_status(tid)
    return render_template('dochazka.html', view=view,
                           filters={'range': rng, 'etype': etype},
                           is_coach=(get_team_role() == 'coach'), tymuj_status=tymuj_status)


@bp.route('/calendar/add', methods=['POST'], endpoint='calendar_add')
def calendar_add():
    # coach-only
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    day_s = (request.form.get('day') or '').strip()
    # prefer dropdowns hour/min, fallback to time string
    hh = (request.form.get('time_hour') or '').strip()
    mm = (request.form.get('time_minute') or '').strip()
    if len(hh) == 2 and len(mm) == 2 and hh.isdigit() and mm.isdigit():
        time_s = f"{hh}:{mm}"
    else:
        time_s = (request.form.get('time') or '').strip()
    title = (request.form.get('title') or 'Trénink').strip() or 'Trénink'
    try:
        d = date.fromisoformat(day_s)
    except Exception:
        flash('Neplatné datum.', 'error')
        return redirect(request.referrer or url_for('home'))
    kind = (request.form.get('kind') or 'training')[:20]
    tid = get_team_id()
    repeat = (request.form.get('repeat') or 'none').strip()

    from coach.services import recurrence as rec
    if repeat in rec.FREQUENCIES:
        weekdays = [w for w in request.form.getlist('weekday') if w in rec.WEEKDAYS]
        until = None
        until_s = (request.form.get('until') or '').strip()
        if until_s:
            try:
                until = date.fromisoformat(until_s)
            except Exception:
                until = None
        try:
            count = int(request.form.get('count') or 0)
        except Exception:
            count = 0
        if count < 0:
            count = 0
        if not until and not count:
            flash('U opakování zadej datum „do“ nebo počet opakování.', 'error')
            return redirect(request.referrer or url_for('home'))
        # One end condition. If a count is given it is authoritative — a stray/near
        # "until" must never silently truncate the requested number of occurrences.
        if count:
            until = None
        dates, capped = rec.generate_dates(d, repeat, weekdays=weekdays, until=until,
                                           count=(count or None))
        if not dates:
            flash('Opakování nevygenerovalo žádné události. Zkontroluj nastavení.', 'error')
            return redirect(request.referrer or url_for('home'))
        import uuid
        series_id = uuid.uuid4().hex
        rule = rec.build_rule(repeat, weekdays)
        for od in dates:
            db.session.add(TrainingEvent(team_id=tid, day=od, time=time_s[:10], title=title[:200],
                                         kind=kind, series_id=series_id, recurrence_rule=rule,
                                         source='coachhub_recurring'))
        db.session.commit()
        # Týmuj overlap warning (does not block; never overwrites external events)
        try:
            cached_days = {date.fromisoformat(it.get('day')) for it in
                           (tymuj_svc._cache_payload(tid).get('events') or []) if it.get('day')}
            if cached_days & set(dates):
                flash('Pozor: některé termíny se kryjí s událostmi z Týmuj kalendáře.', 'info')
        except Exception:
            pass
        n = len(dates)
        if n == 1:
            flash('Vytvořena pouze 1 událost — zkontroluj počet opakování, vybrané dny '
                  'a koncové datum.', 'info')
        else:
            msg = 'Vytvořeno %d opakovaných událostí.' % n
            if capped:
                msg += ' Dosažen limit %d; zkrať období nebo počet.' % rec.MAX_OCCURRENCES
            flash(msg, 'success' if not capped else 'info')
        return redirect(url_for('home', year=d.year, month=d.month))

    ev = TrainingEvent(team_id=tid, day=d, time=time_s[:10], title=title[:200], kind=kind,
                       source='coachhub_manual')
    db.session.add(ev)
    db.session.commit()
    flash('Trénink byl přidán do kalendáře.', 'success')
    return redirect(url_for('home', year=d.year, month=d.month))


@bp.route('/calendar/update', methods=['POST'], endpoint='calendar_update')
def calendar_update():
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    try:
        ev_id = int(request.form.get('id') or '0')
    except Exception:
        ev_id = 0
    ev = TrainingEvent.query.get(ev_id)
    if not ev or ev.team_id != get_team_id():
        flash('Událost nebyla nalezena.', 'error')
        return redirect(request.referrer or url_for('home'))
    title = (request.form.get('title') or ev.title).strip()
    hh = (request.form.get('time_hour') or '').strip()
    mm = (request.form.get('time_minute') or '').strip()
    if len(hh) == 2 and len(mm) == 2 and hh.isdigit() and mm.isdigit():
        time_s = f"{hh}:{mm}"
    else:
        time_s = (request.form.get('time') or (ev.time or '')).strip()
    kind = (request.form.get('kind') or (ev.kind or 'training')).strip()
    kind = kind if kind in ('training', 'match') else (ev.kind or 'training')
    new_title = title[:200] or ev.title
    new_time = time_s[:10]
    # Scope for recurring series: one (default) | future | series
    scope = (request.form.get('scope') or 'one').strip()
    targets = [ev]
    if ev.series_id and scope in ('future', 'series'):
        q = TrainingEvent.query.filter_by(team_id=ev.team_id, series_id=ev.series_id)
        if scope == 'future':
            q = q.filter(TrainingEvent.day >= ev.day)
        targets = q.all()
    for t in targets:
        t.title = new_title
        t.time = new_time
        t.kind = kind
    db.session.commit()
    flash('Upraveno %d událostí.' % len(targets) if len(targets) > 1 else 'Událost byla upravena.', 'success')
    return redirect(url_for('home', year=ev.day.year, month=ev.day.month))


@bp.route('/calendar/delete', methods=['POST'], endpoint='calendar_delete')
def calendar_delete():
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    try:
        ev_id = int(request.form.get('id') or '0')
    except Exception:
        ev_id = 0
    ev = TrainingEvent.query.get(ev_id)
    if not ev or ev.team_id != get_team_id():
        flash('Událost nebyla nalezena.', 'error')
        return redirect(request.referrer or url_for('home'))
    y, m = ev.day.year, ev.day.month
    scope = (request.form.get('scope') or 'one').strip()
    targets = [ev]
    if ev.series_id and scope in ('future', 'series'):
        q = TrainingEvent.query.filter_by(team_id=ev.team_id, series_id=ev.series_id)
        if scope == 'future':
            q = q.filter(TrainingEvent.day >= ev.day)
        targets = q.all()
    n = len(targets)
    # Delete each occurrence's attendance too, otherwise the rows are orphaned and
    # SQLite reuses the freed TrainingEvent id -> a future event inherits the old
    # attendance via the colliding 'local:<id>' key. Clean up keeps keys unique.
    keys = ['local:%d' % t.id for t in targets]
    if keys:
        AttendanceEntry.query.filter(
            AttendanceEntry.team_id == ev.team_id,
            AttendanceEntry.event_key.in_(keys)
        ).delete(synchronize_session=False)
    for t in targets:
        db.session.delete(t)
    db.session.commit()
    flash('Smazáno %d událostí.' % n if n > 1 else 'Událost byla smazána.', 'success')
    return redirect(url_for('home', year=y, month=m))


MAX_MESSAGE_LEN = 500


@bp.route('/message/post', methods=['POST'], endpoint='message_post')
@team_login_required
def message_post():
    """Post a team message to the message board (coach or player)."""
    text = (request.form.get('text') or '').strip()
    if not text:
        return redirect(request.referrer or url_for('home'))
    try:
        # Do not mutate session role here; just read current role for message meta
        from coach.auth_utils import get_team_role
        role = get_team_role()
        tid = get_team_id()
        if not tid:
            return redirect(request.referrer or url_for('home'))
        # store in AuditEvent as event='message' with meta JSON
        if len(text) > MAX_MESSAGE_LEN:
            text = text[:MAX_MESSAGE_LEN]
        meta = { 'text': text, 'role': role, 'pinned': False }
        from json import dumps
        ev = AuditEvent(event='message', team_id=tid, role=role, meta=dumps(meta))
        db.session.add(ev)
        db.session.commit()
    except Exception:
        pass
    return redirect(request.referrer or url_for('home'))


@bp.route('/message/delete/<int:msg_id>', methods=['POST'], endpoint='message_delete')
@team_login_required
def message_delete(msg_id: int):
    """Delete a team message (coach only)."""
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    tid = get_team_id()
    if not tid:
        return redirect(request.referrer or url_for('home'))
    ev = AuditEvent.query.get_or_404(msg_id)
    if ev.team_id != tid or ev.event != 'message':
        return redirect(request.referrer or url_for('home'))
    try:
        db.session.delete(ev)
        db.session.commit()
    except Exception:
        pass
    return redirect(request.referrer or url_for('home'))


@bp.route('/message/pin/<int:msg_id>', methods=['POST'], endpoint='message_pin')
@team_login_required
def message_pin(msg_id: int):
    """Toggle pin on a message (coach only)."""
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    tid = get_team_id()
    if not tid:
        return redirect(request.referrer or url_for('home'))
    ev = AuditEvent.query.get_or_404(msg_id)
    if ev.team_id != tid or ev.event != 'message':
        return redirect(request.referrer or url_for('home'))
    from json import loads, dumps
    try:
        payload = loads(ev.meta or '{}') if ev.meta else {}
    except Exception:
        payload = {}
    payload['pinned'] = not bool(payload.get('pinned'))
    try:
        ev.meta = dumps(payload)
        db.session.commit()
    except Exception:
        pass
    return redirect(request.referrer or url_for('home'))
