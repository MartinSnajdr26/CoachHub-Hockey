from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, send_file
from flask_login import current_user
from coach.extensions import db
from coach.auth_utils import team_login_required, get_team_id, coach_required
from coach.models import Roster, LineAssignment, Player, LineupSession
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import uuid
import os

bp = Blueprint('lines', __name__)


def _current_line_assignments():
    tid = get_team_id()
    if not tid:
        return {}
    assigns = {a.slot: a.player_id for a in LineAssignment.query.filter_by(team_id=tid).all()}
    players = {p.id: p for p in Player.query.filter_by(team_id=tid).all()}
    return {slot: players.get(pid) for slot, pid in assigns.items()}


def _compose_lines_pdf(title: str) -> str:
    export_dir = current_app.config['EXPORT_FOLDER']
    page = Image.new('RGB', (595, 842), 'white')
    draw = ImageDraw.Draw(page)
    try:
        font_title = ImageFont.truetype('arial.ttf', 18)
        font_h = ImageFont.truetype('arial.ttf', 14)
        font_b = ImageFont.truetype('arial.ttf', 12)
    except Exception:
        font_title = ImageFont.load_default()
        font_h = ImageFont.load_default()
        font_b = ImageFont.load_default()
    margin = 36
    y = margin
    draw.text((margin, y), title or 'Sestava', fill=(0, 0, 0), font=font_title)
    y += 28
    assigns = _current_line_assignments()

    def nm(p):
        return p.name if p else '-'

    for line in range(1, 5):
        draw.text((margin, y), f"{line}. lajna", fill=(0, 0, 0), font=font_h)
        y += 18
        lw = nm(assigns.get(f"L{line}LW"))
        c = nm(assigns.get(f"L{line}C"))
        rw = nm(assigns.get(f"L{line}RW"))
        draw.text((margin, y), f"Útok: {lw} – {c} – {rw}", fill=(0, 0, 0), font=font_b)
        y += 16
        ld = nm(assigns.get(f"D{line}LD"))
        rd = nm(assigns.get(f"D{line}RD"))
        draw.text((margin, y), f"Obrana: {ld} – {rd}", fill=(0, 0, 0), font=font_b)
        y += 22
    y += 8
    draw.text((margin, y), 'Brankáři', fill=(0, 0, 0), font=font_h)
    y += 18
    g1 = nm(assigns.get('G1'))
    g2 = nm(assigns.get('G2'))
    draw.text((margin, y), f"G1: {g1}", fill=(0, 0, 0), font=font_b)
    y += 16
    draw.text((margin, y), f"G2: {g2}", fill=(0, 0, 0), font=font_b)
    y += 16
    ts = datetime.now().strftime('%Y%m%d-%H%M%S')
    token = uuid.uuid4().hex[:6]
    filename = f"lineup-{ts}-{token}.pdf"
    out_path = os.path.join(export_dir, filename)
    page.save(out_path, format='PDF')
    return filename


@bp.route('/lines', methods=['GET', 'POST'], endpoint='lines')
@team_login_required
def lines():
    if request.method == 'POST':
        resp = coach_required(lambda: None)()
        if resp is not None:
            return resp
        team_id = get_team_id()
        if not team_id:
            flash('Nemáš přiřazený tým.', 'error')
            return redirect(url_for('lines'))
        LineAssignment.query.filter_by(team_id=team_id).delete()
        db.session.commit()
        for slot, pid in request.form.items():
            if slot == 'csrf_token' or not pid:
                continue
            try:
                player_id = int(pid)
            except Exception:
                continue
            db.session.add(LineAssignment(player_id=player_id, slot=slot, team_id=team_id))
        db.session.commit()
        return redirect(url_for('lines'))

    tid = get_team_id()
    roster = Roster.query.filter_by(team_id=tid).all() if tid else []
    assignments = {}
    if tid:
        assignments = {a.slot: a.player_id for a in LineAssignment.query.filter_by(team_id=tid).all()}
    return render_template('lines.html', roster=roster, assignments=assignments)


@bp.route('/lines/export_pdf', methods=['POST'], endpoint='export_lines_pdf')
@team_login_required
def export_lines_pdf():
    from coach.services.exports import cleanup_exports
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    opponent = (request.form.get('opponent') or '').strip()
    date = (request.form.get('date') or datetime.now().strftime('%Y-%m-%d')).strip()
    title = f'Sestava - Zápas - "{opponent}" - {date}'
    filename = _compose_lines_pdf(title)
    sess = LineupSession(title=title, filename=filename, team_id=(get_team_id()))
    db.session.add(sess)
    db.session.commit()
    cleanup_exports()
    return redirect(url_for('drills_export_result', file=filename))


@bp.route('/lineup-sessions', endpoint='lineup_sessions')
@team_login_required
def lineup_sessions():
    # using imported LineupSession
    lq = LineupSession.query
    tid = get_team_id()
    if tid:
        lq = lq.filter(LineupSession.team_id == tid)
    sessions = lq.order_by(LineupSession.created_at.desc()).all()
    return render_template('lineup_sessions.html', sessions=sessions)


@bp.route('/lineup-sessions/delete/<int:sess_id>', methods=['POST'], endpoint='delete_lineup_session')
@team_login_required
def delete_lineup_session(sess_id):
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    sess = LineupSession.query.get_or_404(sess_id)
    if sess.team_id != get_team_id():
        flash('Nemáš oprávnění smazat tuto sestavu.', 'error')
        return redirect(url_for('lineup_sessions'))
    export_dir = current_app.config['EXPORT_FOLDER']
    fpath = os.path.join(export_dir, sess.filename)
    try:
        if os.path.isfile(fpath):
            os.remove(fpath)
    except Exception:
        pass
    db.session.delete(sess)
    db.session.commit()
    return redirect(url_for('lineup_sessions'))
