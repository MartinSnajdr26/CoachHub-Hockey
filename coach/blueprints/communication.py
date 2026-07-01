"""Communication 2.0 — modern team message feed (Nástěnka).

Backward compatible with the existing message board: messages are stored as
AuditEvent(event='message', meta=JSON). This evolution extends the JSON with
category, nickname, important, reactions and an anonymous ownership token. No
schema change. The legacy dashboard widget keeps working on the same rows.
"""
import json
import re
import uuid
from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo
    _PRAGUE = ZoneInfo("Europe/Prague")
except Exception:
    _PRAGUE = None


def _to_prague(dt):
    """Naive UTC (storage convention) -> Europe/Prague aware (DST-safe)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_PRAGUE) if _PRAGUE else dt

from flask import (Blueprint, render_template, request, redirect, url_for, jsonify)

from coach.auth_utils import team_login_required, coach_required, get_team_id, get_team_role
from coach.extensions import db
from coach.models import AuditEvent

bp = Blueprint('communication', __name__)

NICK_MAX = 30
MSG_MAX = 500
EDIT_WINDOW = 15 * 60  # seconds players may edit/delete their own post
CATEGORIES = {
    'announcement': ('📢', 'Oznámení'),
    'practice': ('🏒', 'Trénink'),
    'game': ('🥅', 'Zápas'),
    'payments': ('💰', 'Platby'),
    'question': ('❓', 'Dotaz'),
    'general': ('💬', 'Obecné'),
}
REACTIONS = ('like', 'thanks', 'funny', 'question')
_CTRL_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')


def _clean(s, maxlen):
    s = _CTRL_RE.sub('', (s or '')).strip()
    return s[:maxlen]


def _role_name(role):
    return 'Trenér' if role == 'coach' else 'Hráč'


def _load(ev):
    try:
        return json.loads(ev.meta or '{}') if ev.meta else {}
    except Exception:
        return {}


def _view(ev):
    m = _load(ev)
    cat = m.get('category') if m.get('category') in CATEGORIES else 'general'
    nick = (m.get('nickname') or '').strip() or _role_name(m.get('role') or ev.role)
    reactions = m.get('reactions') or {}
    now = datetime.utcnow()
    age = int((now - ev.created_at).total_seconds()) if ev.created_at else 10 ** 9
    # Display in Europe/Prague (DST-safe); created_at is stored naive UTC.
    when_label = ''
    if ev.created_at:
        d = _to_prague(ev.created_at)
        nowp = _to_prague(now)
        if d.date() == nowp.date():
            when_label = 'Dnes ' + d.strftime('%H:%M')
        elif (nowp.date() - d.date()).days == 1:
            when_label = 'Včera ' + d.strftime('%H:%M')
        else:
            when_label = d.strftime('%d.%m.%Y %H:%M')
    return {
        'id': ev.id,
        'text': m.get('text') or '',
        'nickname': nick,
        'role': m.get('role') or ev.role or 'player',
        'category': cat,
        'pub': m.get('pub') or '',
        'cat_emoji': CATEGORIES[cat][0],
        'cat_label': CATEGORIES[cat][1],
        'pinned': bool(m.get('pinned')),
        'important': bool(m.get('important')),
        'reactions': {r: int(reactions.get(r, 0) or 0) for r in REACTIONS},
        'created_at': ev.created_at,
        'when_label': when_label,
        'age': age,
        'editable_window': age < EDIT_WINDOW,
    }


def _messages(tid):
    rows = (AuditEvent.query.filter_by(team_id=tid, event='message')
            .order_by(AuditEvent.created_at.desc()).limit(300).all())
    views = [_view(r) for r in rows]
    views.sort(key=lambda v: (not v['pinned'], -(v['created_at'].timestamp() if v['created_at'] else 0)))
    return views


def _get_msg(tid, msg_id):
    ev = AuditEvent.query.get(msg_id)
    if not ev or ev.team_id != tid or ev.event != 'message':
        return None
    return ev


def _can_modify(ev, role):
    """Coach may modify any message; a player only their own (matching token)
    within the edit window."""
    if role == 'coach':
        return True
    m = _load(ev)
    token = (request.form.get('token') or (request.get_json(silent=True) or {}).get('token') or '').strip()
    if not token or token != (m.get('token') or ''):
        return False
    age = (datetime.utcnow() - ev.created_at).total_seconds() if ev.created_at else 10 ** 9
    return age < EDIT_WINDOW


# ----------------------------- views -----------------------------
@bp.route('/nastenka', methods=['GET'], endpoint='feed')
@team_login_required
def feed():
    tid = get_team_id()
    if not tid:
        return redirect(url_for('team_auth'))
    return render_template('nastenka.html',
                           messages=_messages(tid),
                           categories=CATEGORIES,
                           is_coach=(get_team_role() == 'coach'))


@bp.route('/nastenka/post', methods=['POST'], endpoint='post')
@team_login_required
def post():
    tid = get_team_id()
    if not tid:
        return redirect(url_for('team_auth'))
    role = get_team_role()
    text = _clean(request.form.get('text'), MSG_MAX)
    if not text:
        return redirect(url_for('communication.feed'))
    nickname = _clean(request.form.get('nickname'), NICK_MAX) or _role_name(role)
    category = request.form.get('category')
    if category not in CATEGORIES:
        category = 'general'
    meta = {
        'text': text, 'role': role, 'nickname': nickname, 'category': category,
        'pinned': bool(request.form.get('pinned')) if role == 'coach' else False,
        'important': bool(request.form.get('important')) if role == 'coach' else False,
        'reactions': {}, 'token': (request.form.get('token') or uuid.uuid4().hex)[:40],
        'pub': (request.form.get('pub') or uuid.uuid4().hex)[:40],
    }
    db.session.add(AuditEvent(event='message', team_id=tid, role=role, meta=json.dumps(meta, ensure_ascii=False)))
    db.session.commit()
    return redirect(url_for('communication.feed'))


@bp.route('/nastenka/edit/<int:msg_id>', methods=['POST'], endpoint='edit')
@team_login_required
def edit(msg_id):
    tid = get_team_id()
    ev = _get_msg(tid, msg_id)
    if not ev:
        return redirect(url_for('communication.feed'))
    if not _can_modify(ev, get_team_role()):
        return redirect(url_for('communication.feed'))
    text = _clean(request.form.get('text'), MSG_MAX)
    if text:
        m = _load(ev)
        m['text'] = text
        ev.meta = json.dumps(m, ensure_ascii=False)
        db.session.commit()
    return redirect(url_for('communication.feed'))


@bp.route('/nastenka/delete/<int:msg_id>', methods=['POST'], endpoint='delete')
@team_login_required
def delete(msg_id):
    tid = get_team_id()
    ev = _get_msg(tid, msg_id)
    if not ev:
        return redirect(url_for('communication.feed'))
    if not _can_modify(ev, get_team_role()):
        return redirect(url_for('communication.feed'))
    db.session.delete(ev)
    db.session.commit()
    return redirect(url_for('communication.feed'))


def _coach_toggle(msg_id, field):
    tid = get_team_id()
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    ev = _get_msg(tid, msg_id)
    if ev:
        m = _load(ev)
        m[field] = not bool(m.get(field))
        ev.meta = json.dumps(m, ensure_ascii=False)
        db.session.commit()
    return redirect(url_for('communication.feed'))


@bp.route('/nastenka/pin/<int:msg_id>', methods=['POST'], endpoint='pin')
@team_login_required
def pin(msg_id):
    return _coach_toggle(msg_id, 'pinned')


@bp.route('/nastenka/important/<int:msg_id>', methods=['POST'], endpoint='important')
@team_login_required
def important(msg_id):
    return _coach_toggle(msg_id, 'important')


@bp.route('/nastenka/react/<int:msg_id>', methods=['POST'], endpoint='react')
@team_login_required
def react(msg_id):
    """One reaction per browser (enforced client-side via localStorage). The
    client sends the new reaction and the previous one (if switching/removing)."""
    tid = get_team_id()
    ev = _get_msg(tid, msg_id)
    if not ev:
        return jsonify({'ok': False, 'error': 'not_found'}), 404
    data = request.get_json(silent=True) or request.form
    reaction = (data.get('reaction') or '').strip()
    prev = (data.get('prev') or '').strip()
    if reaction and reaction not in REACTIONS:
        return jsonify({'ok': False, 'error': 'bad_reaction'}), 400
    m = _load(ev)
    r = m.get('reactions') or {}
    if prev in REACTIONS:
        r[prev] = max(0, int(r.get(prev, 0) or 0) - 1)
    if reaction in REACTIONS:
        r[reaction] = int(r.get(reaction, 0) or 0) + 1
    m['reactions'] = r
    ev.meta = json.dumps(m, ensure_ascii=False)
    db.session.commit()
    return jsonify({'ok': True, 'reactions': {k: int(r.get(k, 0) or 0) for k in REACTIONS}})
