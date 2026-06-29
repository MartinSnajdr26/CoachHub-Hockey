"""Pokladna — very simple team payment tracker (coach-only).

One monthly contribution record (PaymentPeriod) + one status per player per
month (PaymentStatus). No bank integration / gateways / variable symbols /
matching — those are Pokladna 2.0.
"""
from datetime import date, datetime

from flask import (Blueprint, render_template, request, redirect, url_for, flash, jsonify)

from coach.auth_utils import team_login_required, coach_required, get_team_id, get_team_role
from coach.extensions import db
from coach.models import Player, PaymentPeriod, PaymentStatus

bp = Blueprint('pokladna', __name__)

STATUSES = ('paid', 'partial', 'unpaid')
_CS_MONTHS = ['', 'Leden', 'Únor', 'Březen', 'Duben', 'Květen', 'Červen',
              'Červenec', 'Srpen', 'Září', 'Říjen', 'Listopad', 'Prosinec']


def _coach_gate():
    """Returns a redirect response if the current user is not a coach, else None."""
    return coach_required(lambda: None)()


def _month_label(year, month):
    return '%s %d' % (_CS_MONTHS[month] if 1 <= month <= 12 else str(month), year)


def _get_or_create_period(tid, year, month, create=False):
    p = PaymentPeriod.query.filter_by(team_id=tid, year=year, month=month).first()
    if p or not create:
        return p
    # carry the amount over from the most recent prior period (else 0)
    prev = (PaymentPeriod.query.filter_by(team_id=tid)
            .order_by(PaymentPeriod.year.desc(), PaymentPeriod.month.desc()).first())
    p = PaymentPeriod(team_id=tid, year=year, month=month,
                      amount=(prev.amount if prev else 0), created_at=datetime.utcnow())
    db.session.add(p)
    db.session.commit()
    return p


def _status_map(period):
    if not period:
        return {}
    return {s.player_id: s.status for s in PaymentStatus.query.filter_by(period_id=period.id).all()}


def _summary(period, players):
    smap = _status_map(period)
    total = len(players)
    paid = sum(1 for p in players if smap.get(p.id) == 'paid')
    partial = sum(1 for p in players if smap.get(p.id) == 'partial')
    unpaid = total - paid - partial
    return {'paid': paid, 'partial': partial, 'unpaid': unpaid, 'total': total}


@bp.route('/pokladna', methods=['GET'], endpoint='pokladna')
@team_login_required
def pokladna():
    resp = _coach_gate()
    if resp is not None:
        return resp
    tid = get_team_id()
    if not tid:
        return redirect(url_for('team_auth'))
    today = date.today()
    return _render_period(tid, today.year, today.month, create=True)


@bp.route('/pokladna/<int:year>/<int:month>', methods=['GET'], endpoint='pokladna_month')
@team_login_required
def pokladna_month(year, month):
    resp = _coach_gate()
    if resp is not None:
        return resp
    tid = get_team_id()
    if not tid or not (1 <= month <= 12):
        return redirect(url_for('pokladna.pokladna'))
    return _render_period(tid, year, month, create=False)


def _render_period(tid, year, month, create):
    today = date.today()
    period = _get_or_create_period(tid, year, month, create=create)
    players = Player.query.filter_by(team_id=tid).order_by(Player.name.asc()).all()
    smap = _status_map(period)
    rows = [{'player': p, 'status': smap.get(p.id, 'unpaid')} for p in players]
    is_current = (year == today.year and month == today.month)
    summary = _summary(period, players)
    # history (recent periods)
    periods = (PaymentPeriod.query.filter_by(team_id=tid)
               .order_by(PaymentPeriod.year.desc(), PaymentPeriod.month.desc()).limit(24).all())
    history = []
    for pr in periods:
        s = _summary(pr, players)
        history.append({
            'period': pr, 'label': _month_label(pr.year, pr.month),
            'paid': s['paid'], 'total': s['total'],
            'open': (pr.year == today.year and pr.month == today.month),
            'is_viewed': (pr.id == period.id) if period else False,
        })
    return render_template('pokladna.html',
                           period=period, year=year, month=month,
                           month_label=_month_label(year, month),
                           rows=rows, summary=summary, is_current=is_current,
                           history=history, is_coach=(get_team_role() == 'coach'))


@bp.route('/pokladna/amount', methods=['POST'], endpoint='pokladna_amount')
@team_login_required
def pokladna_amount():
    resp = _coach_gate()
    if resp is not None:
        return resp
    tid = get_team_id()
    try:
        period_id = int(request.form.get('period_id') or 0)
        amount = int(request.form.get('amount') or 0)
    except (TypeError, ValueError):
        flash('Neplatná částka.', 'error')
        return redirect(url_for('pokladna.pokladna'))
    if amount < 0:
        amount = 0
    period = PaymentPeriod.query.filter_by(id=period_id, team_id=tid).first()
    if not period:
        flash('Období nebylo nalezeno.', 'error')
        return redirect(url_for('pokladna.pokladna'))
    period.amount = amount
    db.session.commit()
    flash('Částka byla uložena.', 'success')
    return redirect(url_for('pokladna.pokladna_month', year=period.year, month=period.month))


@bp.route('/pokladna/status', methods=['POST'], endpoint='pokladna_status')
@team_login_required
def pokladna_status():
    """AJAX: set one player's status for a period. Coach-only, JSON in/out."""
    resp = _coach_gate()
    if resp is not None:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    tid = get_team_id()
    data = request.get_json(silent=True) or request.form
    try:
        period_id = int(data.get('period_id') or 0)
        player_id = int(data.get('player_id') or 0)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'bad_input'}), 400
    status = (data.get('status') or '').strip().lower()
    if status not in STATUSES:
        return jsonify({'ok': False, 'error': 'bad_status'}), 400
    period = PaymentPeriod.query.filter_by(id=period_id, team_id=tid).first()
    player = Player.query.filter_by(id=player_id, team_id=tid).first()
    if not period or not player:
        return jsonify({'ok': False, 'error': 'not_found'}), 404
    row = PaymentStatus.query.filter_by(period_id=period.id, player_id=player.id).first()
    if not row:
        row = PaymentStatus(team_id=tid, period_id=period.id, player_id=player.id)
        db.session.add(row)
    row.status = status
    row.updated_at = datetime.utcnow()
    db.session.commit()
    players = Player.query.filter_by(team_id=tid).all()
    return jsonify({'ok': True, 'status': status, 'player_id': player.id,
                    'summary': _summary(period, players)})
