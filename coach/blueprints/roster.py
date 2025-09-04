from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
from coach.extensions import db
from coach.models import Player, Roster
from coach.auth_utils import team_login_required, get_team_id, coach_required

bp = Blueprint('roster', __name__)


@bp.route('/roster', methods=['GET', 'POST'], endpoint='roster')
@team_login_required
def roster():
    if request.method == 'POST':
        # enforce coach
        resp = coach_required(lambda: None)()
        if resp is not None:
            return resp
        team_id = get_team_id()
        if not team_id:
            flash('Nemáš přiřazený tým.', 'error')
            return redirect(url_for('roster'))
        # clear and save new roster for this team
        Roster.query.filter_by(team_id=team_id).delete()
        db.session.commit()
        selected_ids = request.form.getlist('players')
        for pid in selected_ids:
            entry = Roster(player_id=int(pid), team_id=team_id)
            db.session.add(entry)
        db.session.commit()
        return redirect(url_for('roster'))

    items = []
    roster_ids = []
    players = []
    team_id = get_team_id()
    if team_id:
        players = Player.query.filter_by(team_id=team_id).all()
        items = Roster.query.filter_by(team_id=team_id).all()
        roster_ids = [r.player_id for r in items]
    return render_template('roster.html', players=players, roster=items, roster_ids=roster_ids)


@bp.route('/delete_from_roster/<int:roster_id>', methods=['POST'], endpoint='delete_from_roster')
@team_login_required
def delete_from_roster(roster_id):
    resp = coach_required(lambda: None)()
    if resp is not None:
        return resp
    entry = Roster.query.get(roster_id)
    team_id = get_team_id()
    if entry and team_id and entry.team_id == team_id:
        db.session.delete(entry)
        db.session.commit()
    return redirect(url_for('roster'))
