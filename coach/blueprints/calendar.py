from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
from coach.auth_utils import team_login_required, get_team_id, coach_required
from coach.extensions import db
from datetime import date, datetime, timedelta
import calendar as calmod
from coach.models import TrainingEvent, AuditEvent

bp = Blueprint('calendar', __name__)


@bp.route('/', endpoint='home')
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
    if tid:
        try:
            msgs = (AuditEvent.query
                    .filter(AuditEvent.team_id == tid, AuditEvent.event == 'message')
                    .order_by(AuditEvent.created_at.desc())
                    .limit(50)
                    .all())
            from json import loads
            for m in msgs:
                try:
                    payload = loads(m.meta or '{}') if m.meta else {}
                except Exception:
                    payload = {}
                view_messages.append({
                    'id': m.id,
                    'text': (payload.get('text') or '').strip(),
                    'role': (payload.get('role') or m.role or 'player'),
                    'pinned': bool(payload.get('pinned')),
                    'created_at': m.created_at,
                })
            # Pinned first, then by time desc
            view_messages.sort(key=lambda x: (not x['pinned'], x['created_at']), reverse=True)
        except Exception:
            view_messages = []
    return render_template('home.html',
                           cal_year=y, cal_month=m, month_title=month_title, weeks=weeks,
                           events_by_day=events_by_day,
                           prev_year=prev_y, prev_month=prev_m,
                           next_year=next_y, next_month=next_m,
                           today_label=today_label,
                           today_iso=today.isoformat(),
                           team_messages=view_messages)


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
    ev = TrainingEvent(team_id=get_team_id(), day=d, time=time_s[:10], title=title[:200], kind=(request.form.get('kind') or 'training')[:20])
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
    ev.title = title[:200] or ev.title
    ev.time = time_s[:10]
    ev.kind = kind if kind in ('training','match') else (ev.kind or 'training')
    db.session.commit()
    flash('Událost byla upravena.', 'success')
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
    db.session.delete(ev)
    db.session.commit()
    flash('Událost byla smazána.', 'success')
    return redirect(url_for('home', year=y, month=m))


MAX_MESSAGE_LEN = 500


@bp.route('/message/post', methods=['POST'], endpoint='message_post')
@team_login_required
def message_post():
    """Post a team message to the message board (coach or player)."""
    from flask import session
    text = (request.form.get('text') or '').strip()
    if not text:
        return redirect(request.referrer or url_for('home'))
    try:
        role = session.get('team_role') or 'player'
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
