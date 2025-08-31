from flask import Flask, render_template, request, redirect, url_for, send_file
from flask_sqlalchemy import SQLAlchemy
import os
import io
import uuid
import base64
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)

# --- Nastavení databáze SQLite ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(BASE_DIR, "players.db")
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- Model hráče ---
class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    position = db.Column(db.String(10), nullable=False)  # F, D, G

    def __repr__(self):
        return f"<Player {self.name} ({self.position})>"

# --- Model nominace na zápas ---
class Roster(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey("player.id"))
    player = db.relationship("Player")

class LineAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey("player.id"))
    slot = db.Column(db.String(10))  # např. L1F1, L1F2, D1-1, G1...
    player = db.relationship("Player")

class Drill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    duration = db.Column(db.Integer, nullable=True)  # v minutách
    category = db.Column(db.String(50), nullable=True)
    image_data = db.Column(db.Text, nullable=True)   # obrázek uložený jako base64
    path_data = db.Column(db.Text, nullable=True)    # JSON s daty animace

class TrainingSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(300), nullable=False)  # relativní cesta do static/exports
    drill_ids = db.Column(db.Text, nullable=True)         # CSV nebo JSON se seznamem ID
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class LineupSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)  # Sestava - Zápas - "Soupeř" - datum
    filename = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# --- Kontext pro globální navigaci (kategorie tréninků) ---
@app.context_processor
def inject_drill_nav():
    try:
        cats = db.session.query(Drill.category).distinct().all()
        categories = [c[0] for c in cats if c and c[0]]
    except Exception:
        categories = []
    return { 'nav_drill_categories': categories }


# --- Domovská stránka ---
@app.route("/")
def home():
    return render_template("home.html")

# --- Seznam hráčů ---
@app.route("/players")
def players():
    players = Player.query.all()
    return render_template("players.html", players=players)

@app.route("/add_player", methods=["POST"])
def add_player():
    name = request.form.get("name")
    position = request.form.get("position")
    if name and position in ["F", "D", "G"]:
        new_player = Player(name=name, position=position)
        db.session.add(new_player)
        db.session.commit()
    return redirect(url_for("players"))

@app.route("/delete_player/<int:player_id>", methods=["POST"])
def delete_player(player_id):
    player = Player.query.get(player_id)
    if player:
        db.session.delete(player)
        db.session.commit()
    return redirect(url_for("players"))



# --- Soupiska na zápas ---
@app.route("/roster", methods=["GET", "POST"])
def roster():
    if request.method == "POST":
        # vymazat starou soupisku
        Roster.query.delete()
        db.session.commit()

        # uložit nové hráče
        selected_ids = request.form.getlist("players")
        for pid in selected_ids:
            roster_entry = Roster(player_id=int(pid))
            db.session.add(roster_entry)
        db.session.commit()

        return redirect(url_for("roster"))

    players = Player.query.all()
    roster = Roster.query.all()
    roster_ids = [r.player_id for r in roster]  # seznam ID nominovaných

    return render_template("roster.html", players=players, roster=roster, roster_ids=roster_ids)



@app.route("/lines", methods=["GET", "POST"])
def lines():
    if request.method == "POST":
        # smažeme staré rozdělení
        LineAssignment.query.delete()
        db.session.commit()

        # uložíme nové přiřazení
        for slot, pid in request.form.items():
            if pid:  # pokud něco vybráno
                assignment = LineAssignment(player_id=int(pid), slot=slot)
                db.session.add(assignment)
        db.session.commit()
        return redirect(url_for("lines"))

    roster = Roster.query.all()  # jen nominovaní hráči
    assignments = {a.slot: a.player_id for a in LineAssignment.query.all()}
    return render_template("lines.html", roster=roster, assignments=assignments)


def _current_line_assignments():
    # returns dict slot->Player or None
    assigns = {a.slot: a.player_id for a in LineAssignment.query.all()}
    players = {p.id: p for p in Player.query.all()}
    return {slot: players.get(pid) for slot, pid in assigns.items()}


def _compose_lines_pdf(title: str) -> str:
    # Build one-page PDF with current lines
    export_dir = os.path.join(BASE_DIR, "static", "exports")
    os.makedirs(export_dir, exist_ok=True)
    page = Image.new("RGB", (595, 842), "white")  # A4 @72dpi
    draw = ImageDraw.Draw(page)
    try:
        font_title = ImageFont.truetype("arial.ttf", 18)
        font_h = ImageFont.truetype("arial.ttf", 14)
        font_b = ImageFont.truetype("arial.ttf", 12)
    except Exception:
        font_title = ImageFont.load_default()
        font_h = ImageFont.load_default()
        font_b = ImageFont.load_default()
    margin = 36
    y = margin
    draw.text((margin, y), title or "Sestava", fill=(0,0,0), font=font_title)
    y += 28
    assigns = _current_line_assignments()
    def nm(p):
        return p.name if p else "-"
    # Lines 1..4
    for line in range(1,5):
        draw.text((margin, y), f"{line}. lajna", fill=(0,0,0), font=font_h)
        y += 18
        lw = nm(assigns.get(f"L{line}LW"))
        c  = nm(assigns.get(f"L{line}C"))
        rw = nm(assigns.get(f"L{line}RW"))
        draw.text((margin, y), f"Útok: {lw} – {c} – {rw}", fill=(0,0,0), font=font_b)
        y += 16
        ld = nm(assigns.get(f"D{line}LD"))
        rd = nm(assigns.get(f"D{line}RD"))
        draw.text((margin, y), f"Obrana: {ld} – {rd}", fill=(0,0,0), font=font_b)
        y += 22
    # Goalies
    y += 8
    draw.text((margin, y), "Brankáři", fill=(0,0,0), font=font_h); y += 18
    g1 = nm(assigns.get("G1")); g2 = nm(assigns.get("G2"))
    draw.text((margin, y), f"G1: {g1}", fill=(0,0,0), font=font_b); y += 16
    draw.text((margin, y), f"G2: {g2}", fill=(0,0,0), font=font_b); y += 16
    # Save
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    token = uuid.uuid4().hex[:6]
    filename = f"lineup-{ts}-{token}.pdf"
    out_path = os.path.join(export_dir, filename)
    page.save(out_path, format="PDF")
    return filename


@app.route("/lines/export_pdf", methods=["POST"])
def export_lines_pdf():
    opponent = (request.form.get("opponent") or "").strip()
    date = (request.form.get("date") or datetime.now().strftime("%Y-%m-%d")).strip()
    # Title format: Sestava - Zápas - "souper" - datum
    title = f'Sestava - Zápas - "{opponent}" - {date}'
    filename = _compose_lines_pdf(title)
    sess = LineupSession(title=title, filename=filename)
    db.session.add(sess)
    db.session.commit()
    cleanup_exports()
    return redirect(url_for("drills_export_result", file=filename))


@app.route("/lineup-sessions")
def lineup_sessions():
    sessions = LineupSession.query.order_by(LineupSession.created_at.desc()).all()
    return render_template("lineup_sessions.html", sessions=sessions)


@app.route("/lineup-sessions/delete/<int:sess_id>", methods=["POST"])
def delete_lineup_session(sess_id):
    sess = LineupSession.query.get_or_404(sess_id)
    export_dir = os.path.join(BASE_DIR, "static", "exports")
    fpath = os.path.join(export_dir, sess.filename)
    try:
        if os.path.isfile(fpath):
            os.remove(fpath)
    except Exception:
        pass
    db.session.delete(sess)
    db.session.commit()
    return redirect(url_for('lineup_sessions'))


@app.route("/drill/new")
def new_drill():
    return render_template("new_drill.html")

@app.route("/drill/save", methods=["POST"])
def save_drill():
    name = request.form.get("name")
    description = request.form.get("description")
    duration = request.form.get("duration")
    category = request.form.get("category")
    image_data = request.form.get("image_data")
    path_data = request.form.get("path_data")

    # pokud přišlo prázdné → nastavíme prázdné pole
    if not path_data:
        path_data = "[]"

    drill = Drill(
        name=name,
        description=description,
        duration=int(duration) if duration else None,
        category=category,
        image_data=image_data,
        path_data=path_data   # uložíme JSON jako string
    )
    db.session.add(drill)
    db.session.commit()
    return redirect(url_for("drills"))

@app.route("/drills")
def drills():
    categories = db.session.query(Drill.category).distinct().all()
    categories = [c[0] for c in categories if c[0]]
    return render_template("drills_categories.html", categories=categories)


@app.route("/drills/<category>")
def drills_by_category(category):
    query = request.args.get("q", "")
    drills = Drill.query.filter(Drill.category == category)
    if query:
        drills = drills.filter(
            (Drill.name.ilike(f"%{query}%")) |
            (Drill.description.ilike(f"%{query}%"))
        )
    drills = drills.all()
    return render_template("drills_by_category.html", category=category, drills=drills, query=query)

@app.route("/drill/<int:drill_id>")
def drill_detail(drill_id):
    drill = Drill.query.get_or_404(drill_id)
    return render_template("drill_detail.html", drill=drill)

@app.route("/drill/delete/<int:drill_id>", methods=["POST"])
def delete_drill(drill_id):
    drill = Drill.query.get_or_404(drill_id)
    db.session.delete(drill)
    db.session.commit()
    return redirect(url_for("drills"))


# --- Výběr a export tréninků do PDF ---
@app.route("/drills/select")
def drills_select():
    q = request.args.get("q", "").strip()
    qry = Drill.query
    if q:
        like = f"%{q}%"
        qry = qry.filter((Drill.name.ilike(like)) | (Drill.description.ilike(like)) | (Drill.category.ilike(like)))
    drills = qry.order_by(Drill.category.asc().nullsfirst(), Drill.name.asc()).all()
    default_title = f"Tréninková jednotka {datetime.now().strftime('%Y-%m-%d')}"
    return render_template("drills_select.html", drills=drills, query=q, default_title=default_title)


def _decode_image(data_url: str) -> Image.Image | None:
    try:
        if not data_url:
            return None
        if "," in data_url:
            b64 = data_url.split(",", 1)[1]
        else:
            b64 = data_url
        raw = base64.b64decode(b64)
        im = Image.open(io.BytesIO(raw))
        return im.convert("RGBA")
    except Exception:
        return None


def _compose_page(drill: Drill, im: Image.Image | None, page_size=(595, 842)) -> Image.Image:
    # A4 @ 72 DPI by default: 595x842 pt
    pg = Image.new("RGB", page_size, "white")
    draw = ImageDraw.Draw(pg)
    # Header text
    title = drill.name or "Bez názvu"
    sub = []
    if drill.category:
        sub.append(f"Kategorie: {drill.category}")
    if drill.duration:
        sub.append(f"Doba: {drill.duration} min")
    subline = "  •  ".join(sub)
    desc = (drill.description or "").strip()
    # Fonts (fallback to default)
    try:
        font_title = ImageFont.truetype("arial.ttf", 18)
        font_sub = ImageFont.truetype("arial.ttf", 12)
        font_desc = ImageFont.truetype("arial.ttf", 12)
    except Exception:
        font_title = ImageFont.load_default()
        font_sub = ImageFont.load_default()
        font_desc = ImageFont.load_default()
    margin = 36  # 0.5 inch
    y = margin
    draw.text((margin, y), title, fill=(0, 0, 0), font=font_title)
    y += 24
    if subline:
        draw.text((margin, y), subline, fill=(0, 0, 0), font=font_sub)
        y += 18
    # Description (max 6 lines)
    if desc:
        max_width = page_size[0] - 2 * margin
        words = desc.split()
        lines = []
        cur = ""
        for w in words:
            test = (cur + " " + w).strip()
            if draw.textlength(test, font=font_desc) <= max_width:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
            if len(lines) >= 6:
                break
        if cur and len(lines) < 6:
            lines.append(cur)
        for line in lines:
            draw.text((margin, y), line, fill=(0, 0, 0), font=font_desc)
            y += 16
        y += 8
    # Image area
    top = y
    bottom = page_size[1] - margin
    left = margin
    right = page_size[0] - margin
    if im is not None:
        # flatten alpha onto white
        if im.mode == "RGBA":
            bg = Image.new("RGB", im.size, "white")
            bg.paste(im, mask=im.split()[3])
            im_rgb = bg
        else:
            im_rgb = im.convert("RGB")
        box_w = right - left
        box_h = bottom - top
        # scale preserving ratio
        iw, ih = im_rgb.size
        scale = min(box_w / iw, box_h / ih)
        nw = int(iw * scale)
        nh = int(ih * scale)
        im_resized = im_rgb.resize((nw, nh), Image.LANCZOS)
        ox = left + (box_w - nw) // 2
        oy = top + (box_h - nh) // 2
        pg.paste(im_resized, (ox, oy))
    else:
        note = "(Bez náhledu cvičení)"
        draw.text((left, top), note, fill=(0, 0, 0), font=font_sub)
    return pg


@app.route("/drills/export_pdf", methods=["POST"])
def export_drills_pdf():
    ids = request.form.getlist("drill_ids")
    session_title = (request.form.get("session_title") or "").strip()
    if not ids:
        return redirect(url_for("drills_select"))
    drills = Drill.query.filter(Drill.id.in_([int(i) for i in ids])).order_by(Drill.category.asc().nullsfirst(), Drill.name.asc()).all()
    if not drills:
        return redirect(url_for("drills_select"))
    pages: list[Image.Image] = []
    for d in drills:
        im = _decode_image(d.image_data or "")
        page = _compose_page(d, im)
        pages.append(page)
    # Ulož PDF do static/exports
    export_dir = os.path.join(BASE_DIR, "static", "exports")
    os.makedirs(export_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    token = uuid.uuid4().hex[:8]
    filename = f"drills-{ts}-{token}.pdf"
    path = os.path.join(export_dir, filename)
    if len(pages) == 1:
        pages[0].save(path, format="PDF")
    else:
        pages[0].save(path, save_all=True, append_images=pages[1:], format="PDF")
    # Ulož session (název + seznam drillů)
    if not session_title:
        session_title = f"Tréninková jednotka {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    sess = TrainingSession(title=session_title, filename=filename, drill_ids=",".join(str(d.id) for d in drills))
    db.session.add(sess)
    db.session.commit()
    # Úklid starých exportů (ponecháme pouze soubory navázané na session a čerstvé orphan soubory do retention)
    cleanup_exports()
    # Přesměruj na výsledkovou stránku s odkazy (download / WhatsApp)
    return redirect(url_for("drills_export_result", file=filename))


def cleanup_exports(retention_days: int = 14):
    export_dir = os.path.join(BASE_DIR, "static", "exports")
    try:
        os.makedirs(export_dir, exist_ok=True)
        # seznam souborů referencovaných sessions
        referenced = set(s.filename for s in TrainingSession.query.all())
        try:
            for s in LineupSession.query.all():
                referenced.add(s.filename)
        except Exception:
            pass
        cutoff = datetime.now() - timedelta(days=retention_days)
        for fname in os.listdir(export_dir):
            if not fname.lower().endswith('.pdf'):
                continue
            fpath = os.path.join(export_dir, fname)
            try:
                st = os.stat(fpath)
                mtime = datetime.fromtimestamp(st.st_mtime)
            except Exception:
                continue
            # nemaž referencované soubory
            if fname in referenced:
                continue
            # orphan soubor starší než retention smaž
            if mtime < cutoff:
                try:
                    os.remove(fpath)
                except Exception:
                    pass
    except Exception:
        # v případě chyby úklid přeskoč
        return


@app.route("/drill-sessions")
def drill_sessions():
    sessions = TrainingSession.query.order_by(TrainingSession.created_at.desc()).all()
    # mapování ID -> Drill pro zobrazení
    drills_by_id = {d.id: d for d in Drill.query.all()}
    return render_template("drills_sessions.html", sessions=sessions, drills_by_id=drills_by_id)


@app.route("/drill-sessions/delete/<int:sess_id>", methods=["POST"])
def delete_drill_session(sess_id):
    sess = TrainingSession.query.get_or_404(sess_id)
    # odeber soubor, pokud existuje
    export_dir = os.path.join(BASE_DIR, "static", "exports")
    fpath = os.path.join(export_dir, sess.filename)
    try:
        if os.path.isfile(fpath):
            os.remove(fpath)
    except Exception:
        pass
    db.session.delete(sess)
    db.session.commit()
    return redirect(url_for('drill_sessions'))


@app.route("/drills/export_result")
def drills_export_result():
    filename = request.args.get("file")
    if not filename:
        return redirect(url_for("drills_select"))
    file_url = url_for('static', filename=f'exports/{filename}', _external=False)
    # absolutní URL pro sdílení (pokud je aplikace dostupná zvenčí)
    try:
        abs_url = url_for('static', filename=f'exports/{filename}', _external=True)
    except Exception:
        abs_url = file_url
    return render_template("drills_export_result.html", filename=filename, file_url=file_url, abs_url=abs_url)

@app.route("/delete_from_roster/<int:roster_id>", methods=["POST"])
def delete_from_roster(roster_id):
    roster_entry = Roster.query.get(roster_id)
    if roster_entry:
        db.session.delete(roster_entry)
        db.session.commit()
    return redirect(url_for("roster"))

# --- Úprava hráče ---
@app.route("/edit_player/<int:player_id>", methods=["GET", "POST"])
def edit_player(player_id):
    player = Player.query.get_or_404(player_id)

    if request.method == "POST":
        # aktualizace údajů
        player.name = request.form.get("name")
        player.position = request.form.get("position")
        db.session.commit()
        return redirect(url_for("players"))

    return render_template("edit_player.html", player=player)



# --- Spuštění ---
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
