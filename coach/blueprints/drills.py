from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import current_user
from coach.extensions import db
from coach.auth_utils import team_login_required, coach_required, get_team_id
from coach.models import Drill, TrainingSession
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import base64
import io
import os
import uuid

bp = Blueprint('drills', __name__)


@bp.route('/drill/new', endpoint='new_drill')
@team_login_required
def new_drill():
    # Player may open the editor, but only coach can save
    return render_template('new_drill.html')


@bp.route('/drill/save', methods=['POST'], endpoint='save_drill')
@team_login_required
def save_drill():
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    name = request.form.get('name')
    description = request.form.get('description')
    duration = request.form.get('duration')
    category = request.form.get('category')
    image_data = request.form.get('image_data')
    path_data = request.form.get('path_data') or '[]'
    drill = Drill(
        name=name,
        description=description,
        duration=int(duration) if duration else None,
        category=category,
        image_data=image_data,
        path_data=path_data,
        team_id=(get_team_id())
    )
    db.session.add(drill)
    db.session.commit()
    return redirect(url_for('drills'))


@bp.route('/drills', endpoint='drills')
@team_login_required
def drills():
    # using imported Drill
    q = db.session.query(Drill.category)
    tid = get_team_id()
    if tid:
        q = q.filter(Drill.team_id == tid)
    categories = [c[0] for c in q.distinct().all() if c[0]]
    return render_template('drills_categories.html', categories=categories)


@bp.route('/drills/<category>', endpoint='drills_by_category')
@team_login_required
def drills_by_category(category):
    # using imported Drill
    query = request.args.get('q', '')
    q = Drill.query.filter(Drill.category == category)
    tid = get_team_id()
    if tid:
        q = q.filter(Drill.team_id == tid)
    if query:
        q = q.filter((Drill.name.ilike(f"%{query}%")) | (Drill.description.ilike(f"%{query}%")))
    drills = q.all()
    return render_template('drills_by_category.html', category=category, drills=drills, query=query)


@bp.route('/drill/<int:drill_id>', endpoint='drill_detail')
@team_login_required
def drill_detail(drill_id):
    # using imported Drill
    drill = Drill.query.get_or_404(drill_id)
    tid = get_team_id()
    if tid and drill.team_id != tid:
        flash('Toto cvičení nepatří do vašeho týmu.', 'error')
        return redirect(url_for('drills'))
    return render_template('drill_detail.html', drill=drill)


@bp.route('/drill/delete/<int:drill_id>', methods=['POST'], endpoint='delete_drill')
@team_login_required
def delete_drill(drill_id):
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    drill = Drill.query.get_or_404(drill_id)
    tid = get_team_id()
    if tid and drill.team_id != tid:
        flash('Není povoleno mazat cvičení jiného týmu.', 'error')
        return redirect(url_for('drills'))
    db.session.delete(drill)
    db.session.commit()
    return redirect(url_for('drills'))


@bp.route('/drills/select', endpoint='drills_select')
@team_login_required
def drills_select():
    # using imported Drill
    q = request.args.get('q', '').strip()
    qry = Drill.query
    tid = get_team_id()
    if tid:
        qry = qry.filter(Drill.team_id == tid)
    if q:
        like = f"%{q}%"
        qry = qry.filter((Drill.name.ilike(like)) | (Drill.description.ilike(like)) | (Drill.category.ilike(like)))
    drills = qry.order_by(Drill.category.asc().nullsfirst(), Drill.name.asc()).all()
    default_title = f"Tréninková jednotka {datetime.now().strftime('%Y-%m-%d')}"
    return render_template('drills_select.html', drills=drills, query=q, default_title=default_title)


def _decode_image(data_url: str):
    try:
        if not data_url:
            return None
        b64 = data_url.split(',', 1)[1] if ',' in data_url else data_url
        raw = base64.b64decode(b64)
        im = Image.open(io.BytesIO(raw))
        return im.convert('RGBA')
    except Exception:
        return None


def _compose_page(drill, im, page_size=(595, 842)):
    pg = Image.new('RGB', page_size, 'white')
    draw = ImageDraw.Draw(pg)
    title = drill.name or 'Bez názvu'
    sub = []
    if drill.category: sub.append(f'Kategorie: {drill.category}')
    if drill.duration: sub.append(f'Doba: {drill.duration} min')
    subline = '  •  '.join(sub)
    desc = (drill.description or '').strip()
    try:
        font_title = ImageFont.truetype('arial.ttf', 18)
        font_sub = ImageFont.truetype('arial.ttf', 12)
        font_desc = ImageFont.truetype('arial.ttf', 12)
    except Exception:
        font_title = ImageFont.load_default(); font_sub = ImageFont.load_default(); font_desc = ImageFont.load_default()
    margin = 36
    y = margin
    draw.text((margin, y), title, fill=(0, 0, 0), font=font_title); y += 24
    if subline:
        draw.text((margin, y), subline, fill=(0, 0, 0), font=font_sub); y += 18
    if desc:
        max_width = page_size[0] - 2 * margin
        words = desc.split(); lines = []; cur = ''
        for w in words:
            test = (cur + ' ' + w).strip()
            if draw.textlength(test, font=font_desc) <= max_width: cur = test
            else:
                if cur: lines.append(cur)
                cur = w
            if len(lines) >= 6: break
        if cur and len(lines) < 6: lines.append(cur)
        for line in lines:
            draw.text((margin, y), line, fill=(0, 0, 0), font=font_desc); y += 16
        y += 8
    top = y; bottom = page_size[1] - margin; left = margin; right = page_size[0] - margin
    if im is not None:
        if im.mode == 'RGBA':
            bg = Image.new('RGB', im.size, 'white'); bg.paste(im, mask=im.split()[3]); im_rgb = bg
        else:
            im_rgb = im.convert('RGB')
        box_w = right - left; box_h = bottom - top
        iw, ih = im_rgb.size; scale = min(box_w / iw, box_h / ih)
        nw = int(iw * scale); nh = int(ih * scale)
        im_resized = im_rgb.resize((nw, nh), Image.LANCZOS)
        ox = left + (box_w - nw) // 2; oy = top + (box_h - nh) // 2
        pg.paste(im_resized, (ox, oy))
    else:
        draw.text((left, top), '(Bez náhledu cvičení)', fill=(0, 0, 0), font=font_sub)
    return pg


@bp.route('/drills/export_pdf', methods=['POST'], endpoint='export_drills_pdf')
@team_login_required
def export_drills_pdf():
    from coach.app import coach_required, get_team_id
    from coach.services.exports import cleanup_exports
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    ids = request.form.getlist('drill_ids')
    session_title = (request.form.get('session_title') or '').strip()
    if not ids:
        return redirect(url_for('drills_select'))
    # Parse custom order map
    order_map = {}
    try:
        for k, v in request.form.items():
            if k.startswith('order[') and k.endswith(']'):
                did = int(k[len('order['):-1]); order_map[did] = int(v)
    except Exception:
        order_map = {}
    sel_ids = [int(i) for i in ids]
    q = Drill.query.filter(Drill.id.in_(sel_ids))
    tid = get_team_id()
    if tid:
        q = q.filter(Drill.team_id == tid)
    drills = q.all()
    def order_key(d):
        return (order_map.get(d.id, 10**9), (d.category or ''), (d.name or ''))
    drills.sort(key=order_key)
    if not drills:
        return redirect(url_for('drills_select'))
    pages = []
    for d in drills:
        im = _decode_image(d.image_data or '')
        pages.append(_compose_page(d, im))
    export_dir = current_app.config['EXPORT_FOLDER']
    ts = datetime.now().strftime('%Y%m%d-%H%M%S'); token = uuid.uuid4().hex[:8]
    filename = f'drills-{ts}-{token}.pdf'
    path = os.path.join(export_dir, filename)
    if len(pages) == 1:
        pages[0].save(path, format='PDF')
    else:
        pages[0].save(path, save_all=True, append_images=pages[1:], format='PDF')
    if not session_title:
        session_title = f"Tréninková jednotka {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    sess = TrainingSession(title=session_title, filename=filename, drill_ids=','.join(str(d.id) for d in drills), team_id=(get_team_id()))
    db.session.add(sess); db.session.commit()
    cleanup_exports()
    return redirect(url_for('drills_export_result', file=filename))


@bp.route('/drill-sessions', endpoint='drill_sessions')
@team_login_required
def drill_sessions():
    # List saved TrainingSession entries for current team
    tid = get_team_id()
    sq = TrainingSession.query
    if tid:
        sq = sq.filter(TrainingSession.team_id == tid)
    sessions = sq.order_by(TrainingSession.created_at.desc()).all()
    drills_by_id = {d.id: d for d in Drill.query.all()}
    return render_template('drills_sessions.html', sessions=sessions, drills_by_id=drills_by_id)


@bp.route('/drill-sessions/delete/<int:sess_id>', methods=['POST'], endpoint='delete_drill_session')
@team_login_required
def delete_drill_session(sess_id):
    # Coach only: remove a stored TrainingSession and its file
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    sess = TrainingSession.query.get_or_404(sess_id)
    tid = get_team_id()
    if sess.team_id and tid and sess.team_id != tid:
        flash('Není povoleno mazat záznamy jiného týmu.', 'error')
        return redirect(url_for('drill_sessions'))
    export_dir = current_app.config['EXPORT_FOLDER']
    fpath = os.path.join(export_dir, sess.filename)
    try:
        if os.path.isfile(fpath):
            os.remove(fpath)
    except Exception:
        pass
    db.session.delete(sess)
    db.session.commit()
    return redirect(url_for('drill_sessions'))


@bp.route('/drills/export_result', endpoint='drills_export_result')
def drills_export_result():
    filename = request.args.get('file')
    if not filename:
        return redirect(url_for('drills_select'))
    file_url = url_for('download_export', filename=filename, _external=False)
    try:
        abs_url = url_for('download_export', filename=filename, _external=True)
    except Exception:
        abs_url = file_url
    return render_template('drills_export_result.html', filename=filename, file_url=file_url, abs_url=abs_url)
