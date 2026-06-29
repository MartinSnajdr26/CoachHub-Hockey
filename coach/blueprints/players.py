import unicodedata
import difflib
from flask import Blueprint, render_template, request, redirect, url_for, flash
from coach.extensions import db
from coach.models import Player, Team
from coach.auth_utils import team_login_required, get_team_id, coach_required

bp = Blueprint('players', __name__)

# Position codes used across CoachHub (Player.position).
_POSITIONS = {'F', 'D', 'G'}


def _norm_name(s: str) -> str:
    """Normalise a name for duplicate matching: strip diacritics, lowercase,
    collapse whitespace. Used only in-memory for comparison, never stored."""
    s = unicodedata.normalize('NFKD', (s or '')).encode('ascii', 'ignore').decode('ascii')
    return ' '.join(s.lower().split())


def _classify_name(name: str, existing_players):
    """Classify a Týmuj name against the current roster.

    Returns (status, suggestion):
      - ('exists', player_name)  exact match (case/diacritics/word-order insensitive)
      - ('similar', player_name) close fuzzy match -> suggest instead of duplicating
      - ('new', None)            no match, safe to import
    """
    nt = _norm_name(name)
    tokens = set(nt.split())
    best_name, best_ratio = None, 0.0
    for p in existing_players:
        npn = _norm_name(p.name)
        if nt and (nt == npn or (tokens and tokens == set(npn.split()))):
            return ('exists', p.name)
        ratio = difflib.SequenceMatcher(None, nt, npn).ratio()
        if ratio > best_ratio:
            best_ratio, best_name = ratio, p.name
    if best_ratio >= 0.82:
        return ('similar', best_name)
    return ('new', None)


@bp.route('/players', endpoint='players')
@team_login_required
def players():
    items = []
    team_id = get_team_id()
    if team_id:
        items = Player.query.filter_by(team_id=team_id).all()
    return render_template('players.html', players=items)


@bp.route('/add_player', methods=['POST'], endpoint='add_player')
@team_login_required
def add_player():
    # Enforce coach role via helper
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    name = (request.form.get('name') or '').strip()
    position = request.form.get('position')
    team_id = get_team_id()
    if not (name and position in ['F', 'D', 'G'] and team_id):
        return redirect(url_for('players'))
    existing = Player.query.filter_by(team_id=team_id, name=name).first()
    if existing:
        flash('Hráč s tímto jménem už v týmu existuje.', 'error')
        return redirect(url_for('players'))
    new_player = Player(name=name, position=position, team_id=team_id)
    db.session.add(new_player)
    db.session.commit()
    flash('Hráč byl přidán.', 'success')
    return redirect(url_for('players'))


@bp.route('/delete_player/<int:player_id>', methods=['POST'], endpoint='delete_player')
@team_login_required
def delete_player(player_id):
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    player = Player.query.get(player_id)
    team_id = get_team_id()
    if player and team_id and player.team_id == team_id:
        from coach.models import Roster, LineAssignment, AttendanceEntry
        Roster.query.filter_by(team_id=team_id, player_id=player.id).delete()
        LineAssignment.query.filter_by(team_id=team_id, player_id=player.id).delete()
        AttendanceEntry.query.filter_by(team_id=team_id, player_id=player.id).delete()
        db.session.delete(player)
        db.session.commit()
    return redirect(url_for('players'))


@bp.route('/edit_player/<int:player_id>', methods=['GET', 'POST'], endpoint='edit_player')
@team_login_required
def edit_player(player_id):
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    player = Player.query.get_or_404(player_id)
    team_id = get_team_id()
    if not team_id or player.team_id != team_id:
        flash('Není povoleno upravovat hráče jiného týmu.', 'error')
        return redirect(url_for('players'))
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        position = (request.form.get('position') or '').strip().upper()
        if not name or position not in _POSITIONS:
            flash('Vyplň platné jméno a pozici hráče.', 'error')
            return redirect(url_for('edit_player', player_id=player.id))
        player.name = name[:100]
        player.position = position
        db.session.commit()
        return redirect(url_for('players'))
    return render_template('edit_player.html', player=player)


@bp.route('/players/import/tymuj', methods=['GET', 'POST'], endpoint='import_tymuj')
@team_login_required
def import_tymuj():
    """Import roster players from the team's Týmuj ICS feed (coach only).

    Reuses the existing Týmuj connector (coach.blueprints.calendar) to fetch
    participant names, previews them with duplicate detection, and creates the
    selected players with a coach-assigned position. Stores only name+position.
    """
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    team_id = get_team_id()
    team = Team.query.get(team_id) if team_id else None
    if not team or not team.tymuj_ics_url:
        flash('Pro import z Týmuj nejprve nastav ICS URL v Nastavení.', 'error')
        return redirect(url_for('settings'))

    from coach.services import tymuj as tymuj_svc

    if request.method == 'POST':
        if request.form.get('action') == 'refresh_tymuj':
            ok, msg = tymuj_svc.refresh_cache(team_id, team.tymuj_ics_url)
            flash(msg, 'success' if ok else 'error')
            return redirect(url_for('players.import_tymuj'))
        existing = Player.query.filter_by(team_id=team_id).all()
        existing_norm = {_norm_name(p.name) for p in existing}
        imported, duplicates, ignored = 0, 0, 0
        for idx in request.form.getlist('import_idx'):
            name = (request.form.get('name_' + idx) or '').strip()[:100]
            pos = (request.form.get('pos_' + idx) or '').strip().upper()
            if not name or pos not in _POSITIONS:
                ignored += 1
                continue
            # Re-check duplicates at save time (defensive against stale preview).
            # Existing players are never overwritten -> manual coach edits are safe.
            if _norm_name(name) in existing_norm:
                duplicates += 1
                continue
            db.session.add(Player(name=name, position=pos, team_id=team_id))
            existing_norm.add(_norm_name(name))
            imported += 1
        if imported:
            db.session.commit()
        if imported:
            flash('Importováno %d nových hráčů z Týmuj (duplicity: %d, ignorováno: %d). '
                  'Existující hráči nebyli změněni.' % (imported, duplicates, ignored), 'success')
        elif duplicates or ignored:
            flash('Nebyl importován žádný nový hráč (duplicity: %d, ignorováno: %d).'
                  % (duplicates, ignored), 'info')
        else:
            flash('Nebyl importován žádný hráč.', 'info')
        return redirect(url_for('players'))

    # GET: build preview
    existing = Player.query.filter_by(team_id=team_id).order_by(Player.name.asc()).all()
    tymuj_names = tymuj_svc.get_cached_participants(team_id)
    rows = []
    for i, name in enumerate(tymuj_names):
        status, suggestion = _classify_name(name, existing)
        rows.append({'idx': i, 'name': name, 'status': status, 'suggestion': suggestion})
    counts = {
        'new': sum(1 for r in rows if r['status'] == 'new'),
        'similar': sum(1 for r in rows if r['status'] == 'similar'),
        'exists': sum(1 for r in rows if r['status'] == 'exists'),
    }
    return render_template('players_import_tymuj.html', rows=rows, counts=counts, total=len(rows), tymuj_status=tymuj_svc.get_status(team_id))
