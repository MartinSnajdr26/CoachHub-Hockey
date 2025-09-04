from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
from coach.extensions import db
from coach.models import Player
from coach.auth_utils import team_login_required, get_team_id, coach_required

bp = Blueprint('players', __name__)


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
        player.name = request.form.get('name')
        player.position = request.form.get('position')
        db.session.commit()
        return redirect(url_for('players'))
    return render_template('edit_player.html', player=player)
