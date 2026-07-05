"""CoachHub-first attendance: Týmuj CSV/Excel import + native player attendance.

- Coach: upload -> preview -> confirm import (no writes before confirm),
  import history + rollback.
- Player/Coach: native attendance — pick player + date range, one-tap status.
"""
import csv
import io
import json
from datetime import date, timedelta

import os

from flask import (Blueprint, render_template, request, redirect, url_for, flash,
                   current_app, jsonify, Response, abort)

from coach.auth_utils import team_login_required, coach_required, get_team_id, get_team_role
from coach.extensions import db
from coach.models import Player, AttendanceEntry, AttendanceImport
from coach.services import attendance_import as ai
from coach.services import attendance_stats as stats
from coach.services import attendance_reminder as reminder
from coach.blueprints.calendar import _collect_events_for_team

bp = Blueprint('attendance', __name__)

# Player-facing date filter (simplified): All / Future / Past / Next 30 days.
_RANGES = ('all', 'future', 'past', 'next30')
_DEFAULT_RANGE = 'future'

# Czech month names (nominative for group headings, genitive for day labels).
_CS_MONTHS_NOM = ['', 'Leden', 'Únor', 'Březen', 'Duben', 'Květen', 'Červen',
                  'Červenec', 'Srpen', 'Září', 'Říjen', 'Listopad', 'Prosinec']
_CS_MONTHS_GEN = ['', 'ledna', 'února', 'března', 'dubna', 'května', 'června',
                  'července', 'srpna', 'září', 'října', 'listopadu', 'prosince']
_KIND_LABELS = {'match': 'Zápas', 'training': 'Trénink', 'camp': 'Soustředění'}


def _range_dates(which):
    today = date.today()
    if which == 'past':
        return today - timedelta(days=730), today - timedelta(days=1)
    if which == 'next30':
        return today, today + timedelta(days=30)
    if which == 'all':
        return today - timedelta(days=730), today + timedelta(days=730)
    return today, today + timedelta(days=365)            # future (default)


# ----------------------------- native attendance ------------------------
@bp.route('/attendance', methods=['GET'], endpoint='attendance')
@team_login_required
def attendance():
    tid = get_team_id()
    if not tid:
        return redirect(url_for('team_auth'))
    players = Player.query.filter_by(team_id=tid).order_by(Player.name.asc()).all()
    rng = (request.args.get('range') or _DEFAULT_RANGE).strip()
    if rng not in _RANGES:
        rng = _DEFAULT_RANGE
    start, end = _range_dates(rng)
    try:
        active_player_id = int(request.args.get('player_id') or 0)
    except (TypeError, ValueError):
        active_player_id = 0
    active_player = next((p for p in players if p.id == active_player_id), None)

    today = date.today()
    groups, summary = [], None
    if active_player:
        events = _collect_events_for_team(tid, start, end)
        # past ranges read most-recent-first; future/all chronological
        events.sort(key=lambda e: (e['day'], e.get('time') or ''), reverse=(rng == 'past'))
        rows = AttendanceEntry.query.filter_by(team_id=tid, player_id=active_player.id).all()
        by_key = {r.event_key: r for r in rows}

        counts = {'going': 0, 'not_going': 0, 'maybe': 0, 'unknown': 0}
        upcoming = 0
        cur_label, cur_list = None, None
        for e in events:
            r = by_key.get(e['key'])
            st = r.status if r else 'unknown'
            counts[st] = counts.get(st, 0) + 1
            if e['day'] >= today:
                upcoming += 1
            d = e['day']
            item = {
                'key': e['key'], 'day': d,
                'day_label': '%d. %s' % (d.day, _CS_MONTHS_GEN[d.month]),
                'time': e.get('time') or '', 'title': e.get('title') or '',
                'kind': e.get('kind') or 'training',
                'kind_label': _KIND_LABELS.get(e.get('kind') or 'training', 'Ostatní'),
                'location': e.get('location') or '',
                'is_past': d < today,
                'status': st,
                'source': (r.source if r else None),
                'source_label': (ai.SOURCE_LABELS.get(r.source) if r else None),
            }
            label = '%s %d' % (_CS_MONTHS_NOM[d.month], d.year)
            if label != cur_label:
                cur_label, cur_list = label, []
                groups.append({'label': label, 'events': cur_list})
            cur_list.append(item)
        total = len(events)
        summary = {
            'upcoming': upcoming,
            'going': counts['going'],
            'unknown': counts['unknown'],
            'total': total,
            'pct': round(counts['going'] * 100 / total) if total else 0,
        }
    return render_template('player_attendance.html',
                           players=players, active_player=active_player,
                           groups=groups, summary=summary, rng=rng,
                           is_coach=(get_team_role() == 'coach'),
                           source_labels=ai.SOURCE_LABELS)


def _player_attendance_url():
    """Absolute, production-safe URL to the player-facing attendance page.

    No host is hardcoded — ``url_for`` uses the current request host. The scheme
    is forced to https in production; in dev it mirrors the request scheme.
    """
    if (os.getenv('APP_ENV') or '').strip().lower() == 'production':
        return url_for('attendance.attendance', _external=True, _scheme='https')
    return url_for('attendance.attendance', _external=True)


@bp.route('/attendance/reminder', methods=['GET'], endpoint='attendance_reminder')
@team_login_required
@coach_required
def attendance_reminder():
    """Coach-only: open WhatsApp with a prefilled reminder for the players who
    have not answered a specific event. Nothing is sent automatically and no DB
    record is created. Team isolation: the event and players are resolved from
    the current team only, so one team can never reminder another team's event.
    """
    tid = get_team_id()
    if not tid:
        return redirect(url_for('team_auth'))
    event_key = (request.args.get('event') or '').strip()
    if not event_key:
        abort(404)
    # Resolve the event from THIS team's events only (wide window mirrors the
    # dochazka POST handler) → prevents cross-team event access.
    start_date = date.today() - timedelta(days=45)
    end_date = date.today() + timedelta(days=180)
    event = next((e for e in _collect_events_for_team(tid, start_date, end_date)
                  if e['key'] == event_key), None)
    if event is None:
        abort(404)
    players = Player.query.filter_by(team_id=tid).order_by(Player.name.asc()).all()
    entries = AttendanceEntry.query.filter_by(team_id=tid).all()
    names = reminder.unanswered_player_names(players, entries, event_key)
    if not names:
        flash('Všichni hráči již mají docházku vyplněnou.', 'info')
        return redirect(url_for('dochazka'))
    message = reminder.format_reminder_message(
        event.get('title'), event['day'], event.get('time') or '',
        names, _player_attendance_url())
    return redirect(reminder.whatsapp_share_url(message))


@bp.route('/attendance/set', methods=['POST'], endpoint='attendance_set')
@team_login_required
def attendance_set():
    tid = get_team_id()
    role = get_team_role()
    if not tid:
        return redirect(url_for('team_auth'))
    try:
        player_id = int(request.form.get('player_id') or 0)
    except (TypeError, ValueError):
        player_id = 0
    event_key = (request.form.get('event_key') or '').strip()
    status = (request.form.get('status') or '').strip().lower()
    if status not in ('going', 'not_going', 'maybe', 'unknown'):
        flash('Neplatný stav docházky.', 'error')
        return redirect(request.referrer or url_for('attendance.attendance'))
    player = Player.query.filter_by(id=player_id, team_id=tid).first()
    if not player:
        flash('Hráč nebyl nalezen.', 'error')
        return redirect(request.referrer or url_for('attendance.attendance'))
    # validate the event_key belongs to this team's known events (wide window)
    known = _collect_events_for_team(tid, date.today() - timedelta(days=365),
                                     date.today() + timedelta(days=365))
    meta = next((e for e in known if e['key'] == event_key), None)
    if not meta:
        flash('Událost nebyla nalezena.', 'error')
        return redirect(request.referrer or url_for('attendance.attendance'))
    src = ai.SOURCE_COACH if role == 'coach' else ai.SOURCE_PLAYER
    from datetime import datetime
    now = datetime.utcnow()
    entry = AttendanceEntry.query.filter_by(team_id=tid, player_id=player_id, event_key=event_key).first()
    if not entry:
        entry = AttendanceEntry(team_id=tid, player_id=player_id, event_key=event_key,
                                event_title=(meta.get('title') or '')[:200],
                                event_day=meta.get('day') or date.today(),
                                event_time=(meta.get('time') or '')[:10],
                                event_kind=(meta.get('kind') or 'training')[:20],
                                event_source=(meta.get('source') or 'local')[:20])
        db.session.add(entry)
    entry.status = status
    entry.source = src
    entry.updated_by_role = role
    entry.updated_at = now
    db.session.commit()
    return redirect(request.referrer or url_for('attendance.attendance',
                    player_id=player_id, range=request.form.get('range', 'upcoming')))


@bp.route('/attendance/cell', methods=['POST'], endpoint='attendance_cell')
@team_login_required
def attendance_cell():
    """AJAX coach matrix edit -> set one cell, return the event's fresh summary.
    JSON in/out, no page reload. Coach-only (preserves existing permissions)."""
    resp = coach_required(lambda: None)()
    if resp is not None:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    tid = get_team_id()
    data = request.get_json(silent=True) or request.form
    try:
        player_id = int(data.get('player_id') or 0)
    except (TypeError, ValueError):
        player_id = 0
    event_key = (data.get('event_key') or '').strip()
    status = (data.get('status') or '').strip().lower()
    if status not in ('going', 'not_going', 'maybe', 'unknown'):
        return jsonify({'ok': False, 'error': 'bad_status'}), 400
    player = Player.query.filter_by(id=player_id, team_id=tid).first()
    if not player:
        return jsonify({'ok': False, 'error': 'bad_player'}), 404
    known = _collect_events_for_team(tid, date.today() - timedelta(days=365),
                                     date.today() + timedelta(days=365))
    meta = next((e for e in known if e['key'] == event_key), None)
    if not meta:
        return jsonify({'ok': False, 'error': 'bad_event'}), 404
    from datetime import datetime
    now = datetime.utcnow()
    entry = AttendanceEntry.query.filter_by(team_id=tid, player_id=player_id, event_key=event_key).first()
    if not entry:
        entry = AttendanceEntry(team_id=tid, player_id=player_id, event_key=event_key,
                                event_title=(meta.get('title') or '')[:200],
                                event_day=meta.get('day') or date.today(),
                                event_time=(meta.get('time') or '')[:10],
                                event_kind=(meta.get('kind') or 'training')[:20],
                                event_source=(meta.get('source') or 'local')[:20])
        db.session.add(entry)
    entry.status = status
    entry.source = ai.SOURCE_COACH
    entry.updated_by_role = 'coach'
    entry.updated_at = now
    db.session.commit()
    players = Player.query.filter_by(team_id=tid).all()
    ev_entries = AttendanceEntry.query.filter_by(team_id=tid, event_key=event_key).all()
    return jsonify({'ok': True, 'status': status, 'player_id': player_id,
                    'event_key': event_key,
                    'event_summary': stats.event_summary(players, ev_entries)})


_EXPORT_STATUS = {'going': 'Jdu', 'not_going': 'Nejdu', 'maybe': 'Možná', 'unknown': 'Nevyplněno'}


@bp.route('/attendance/export', endpoint='attendance_export')
@team_login_required
def attendance_export():
    """Export attendance respecting the current filters (range + event type).
    format=long (one row per player×event) or format=matrix (players × events).
    Excel-friendly CSV: UTF-8 BOM + ';' delimiter (no XLSX dependency)."""
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    tid = get_team_id()
    if not tid:
        return redirect(url_for('team_auth'))
    rng = stats.normalize_range(request.args.get('range'))
    etype = (request.args.get('etype') or 'all').strip()
    fmt = (request.args.get('format') or 'long').strip()
    today = date.today()
    start, end = stats.range_window(rng, today)
    events = _collect_events_for_team(tid, start, end)
    if etype in ('training', 'match', 'camp', 'other'):
        events = [e for e in events if (e.get('kind') or 'training') == etype]
    events.sort(key=lambda e: (e['day'], e.get('time') or ''))
    players = Player.query.filter_by(team_id=tid).order_by(Player.name.asc()).all()
    entries = AttendanceEntry.query.filter_by(team_id=tid).all()
    by_key = {(e.player_id, e.event_key): e for e in entries}

    buf = io.StringIO()
    buf.write('﻿')                               # BOM so Excel detects UTF-8
    w = csv.writer(buf, delimiter=';')
    if fmt == 'matrix':
        w.writerow(['Hráč', 'Pozice'] + ['%s %s' % (e['day'].strftime('%d.%m.%Y'), e.get('title') or '')
                                         for e in events])
        for p in players:
            row = [p.name, p.position or '']
            for e in events:
                ent = by_key.get((p.id, e['key']))
                row.append(_EXPORT_STATUS.get(ent.status if ent else 'unknown', ''))
            w.writerow(row)
    else:                                             # long (default)
        w.writerow(['Hráč', 'Pozice', 'Datum', 'Čas', 'Typ', 'Událost',
                    'Stav', 'Zdroj', 'Aktualizováno'])
        for p in players:
            for e in events:
                ent = by_key.get((p.id, e['key']))
                st = ent.status if ent else 'unknown'
                w.writerow([
                    p.name, p.position or '',
                    e['day'].strftime('%d.%m.%Y'), e.get('time') or '',
                    _KIND_LABELS.get(e.get('kind') or 'training', 'Ostatní'),
                    e.get('title') or '',
                    _EXPORT_STATUS.get(st, st),
                    ai.SOURCE_LABELS.get(ent.source) if ent else '',
                    ent.updated_at.strftime('%Y-%m-%d %H:%M') if (ent and ent.updated_at) else '',
                ])
    fname = 'dochazka_%s_%s_%s.csv' % (fmt, rng, today.isoformat())
    return Response(buf.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="%s"' % fname})


# ----------------------------- CSV/Excel import -------------------------
@bp.route('/attendance/import', methods=['GET', 'POST'], endpoint='import_attendance')
@team_login_required
def import_attendance():
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    tid = get_team_id()
    if not tid:
        return redirect(url_for('team_auth'))

    if request.method == 'POST':
        action = (request.form.get('action') or '').strip()
        if action == 'preview':
            f = request.files.get('file')
            if not f or not getattr(f, 'filename', ''):
                flash('Vyber soubor (CSV nebo XLSX).', 'error')
                return redirect(url_for('attendance.import_attendance'))
            data = f.read(ai.MAX_FILE_BYTES + 1)
            try:
                parsed = ai.parse_attendance_file(f.filename, data)
            except ai.AttendanceImportError as e:
                flash(str(e), 'error')
                return redirect(url_for('attendance.import_attendance'))
            preview = ai.build_import_preview(tid, parsed)
            return render_template('attendance_import.html', preview=preview,
                                   plan=json.dumps(parsed, ensure_ascii=False),
                                   filename=f.filename[:200], source_labels=ai.SOURCE_LABELS)
        if action == 'confirm':
            try:
                parsed = json.loads(request.form.get('plan') or '{}')
            except Exception:
                flash('Náhled vypršel, nahraj soubor znovu.', 'error')
                return redirect(url_for('attendance.import_attendance'))
            if not parsed.get('players'):
                flash('Náhled vypršel, nahraj soubor znovu.', 'error')
                return redirect(url_for('attendance.import_attendance'))
            pdec = {k[len('pdec_'):]: v for k, v in request.form.items() if k.startswith('pdec_')}
            edec = {k[len('edec_'):]: v for k, v in request.form.items() if k.startswith('edec_')}
            overwrite = bool(request.form.get('overwrite_imported'))
            try:
                batch = ai.confirm_import(tid, parsed, pdec, edec, role='coach',
                                          overwrite_imported=overwrite,
                                          filename=request.form.get('filename'))
            except Exception as e:
                db.session.rollback()
                current_app.logger.warning('attendance import failed: %s', e)
                flash('Import se nezdařil.', 'error')
                return redirect(url_for('attendance.import_attendance'))
            flash('Import dokončen: %d docházek, %d hráčů, %d událostí (přeskočeno %d, přepsáno %d).'
                  % (batch.attendance_imported, batch.players_created, batch.events_created,
                     batch.skipped, batch.overwritten), 'success')
            return redirect(url_for('attendance.import_history'))
        return redirect(url_for('attendance.import_attendance'))

    return render_template('attendance_import.html', preview=None, plan=None,
                           source_labels=ai.SOURCE_LABELS)


@bp.route('/attendance/import/history', methods=['GET'], endpoint='import_history')
@team_login_required
def import_history():
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    tid = get_team_id()
    batches = ai.recent_imports(tid, limit=50)
    for b in batches:
        try:
            b.warnings_list = json.loads(b.warnings or '[]')
        except Exception:
            b.warnings_list = []
    return render_template('attendance_import_history.html', batches=batches,
                           breakdown=ai.source_breakdown(tid), source_labels=ai.SOURCE_LABELS)


@bp.route('/attendance/import/<int:batch_id>/rollback', methods=['POST'], endpoint='import_rollback')
@team_login_required
def import_rollback(batch_id):
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    tid = get_team_id()
    removed = ai.rollback_import(tid, batch_id)
    flash('Vráceno zpět: odstraněno %d importovaných docházek.' % removed, 'info')
    return redirect(url_for('attendance.import_history'))
