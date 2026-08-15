"""Player identity: onboarding claim, coach approval, passkey register/login.

Design choice (see report): the coach approves BEFORE any credential exists.
The claim is bound to the requesting browser by a random token held in that
browser's session and stored only as a sha256 hash, so an approved claim can be
completed by that browser alone — holding the shared player key is not enough.
"""
import json

from flask import (Blueprint, jsonify, redirect, render_template, request,
                   session, url_for, flash)

from coach.auth_utils import (AUTH_PASSKEY, coach_required, establish_team_session,
                              get_auth_method, get_player_id, get_team_id,
                              get_team_role, team_login_required)
from coach.extensions import db, limiter
from coach.models import PasskeyCredential, Player, PlayerRegistrationRequest, Team
from coach.services import player_identity as ident
from coach.services import webauthn_svc as wa
from coach.services.logging import log_event

bp = Blueprint('playerauth', __name__)

_CLAIM_SESSION_KEY = 'onboarding_claim_token'


def _claim_token() -> str:
    """The current browser's claim token, minting one on first use."""
    tok = session.get(_CLAIM_SESSION_KEY)
    if not tok:
        tok = ident.new_claim_token()
        session[_CLAIM_SESSION_KEY] = tok
    return tok


def _json_error(code: str, status: int = 400):
    return jsonify({'ok': False, 'error': code}), status


# --------------------------------------------------------------- onboarding
@bp.route('/player/onboarding', methods=['GET'], endpoint='onboarding')
@team_login_required
def onboarding():
    """Roster picker + current claim state for a shared-key player session."""
    tid = get_team_id()
    if not tid:
        return redirect(url_for('team_auth'))
    if get_team_role() == 'coach':
        # Coaches manage access instead of claiming an identity.
        return redirect(url_for('playerauth.player_access'))

    req = ident.find_by_claim_token(tid, session.get(_CLAIM_SESSION_KEY) or '')
    state, claimed_player = 'none', None
    if req is not None:
        claimed_player = Player.query.filter_by(id=req.player_id, team_id=tid).first()
        if ident.is_expired(req) and req.status in (PlayerRegistrationRequest.STATUS_PENDING,
                                                    PlayerRegistrationRequest.STATUS_APPROVED):
            state = 'expired'
        else:
            state = req.status

    players = Player.query.filter_by(team_id=tid).order_by(Player.name.asc()).all()
    taken = {p.id for p in players if ident.player_has_active_access(tid, p.id)}
    return render_template(
        'player_onboarding.html',
        players=players, state=state, req=req, claimed_player=claimed_player,
        players_with_access=taken,
        already_verified=get_player_id(),
        secure_context=wa.is_secure_context(),
    )


@bp.route('/player/onboarding/claim', methods=['POST'], endpoint='onboarding_claim')
@team_login_required
@limiter.limit('10 per hour')
def onboarding_claim():
    """Create a PENDING claim. Grants nothing — no session identity is set."""
    tid = get_team_id()
    if not tid or get_team_role() == 'coach':
        return redirect(url_for('team_auth'))
    try:
        player_id = int(request.form.get('player_id') or 0)
    except (TypeError, ValueError):
        player_id = 0

    req, err = ident.create_request(tid, player_id, _claim_token())
    if err:
        flash('Tento hráč nebyl v týmu nalezen.', 'error')
        return redirect(url_for('playerauth.onboarding'))
    # Audit the lifecycle by opaque ids only — never the claimed name.
    log_event('player_access.requested', team_id=tid, role='player',
              message='Player access requested',
              meta={'request_id': req.id, 'player_id': req.player_id})
    flash('Žádost byla odeslána. Počkej, až ji trenér schválí.', 'success')
    return redirect(url_for('playerauth.onboarding'))


@bp.route('/player/onboarding/cancel', methods=['POST'], endpoint='onboarding_cancel')
@team_login_required
def onboarding_cancel():
    """Withdraw this browser's own claim."""
    tid = get_team_id()
    req = ident.find_by_claim_token(tid, session.get(_CLAIM_SESSION_KEY) or '')
    if req is not None and req.status in (PlayerRegistrationRequest.STATUS_PENDING,
                                          PlayerRegistrationRequest.STATUS_APPROVED):
        ident.reject(req, tid)
        log_event('player_access.cancelled', team_id=tid, role='player',
                  message='Player withdrew access request',
                  meta={'request_id': req.id, 'player_id': req.player_id})
    flash('Žádost byla zrušena.', 'info')
    return redirect(url_for('playerauth.onboarding'))


# ------------------------------------------------------------ coach approval
@bp.route('/team/player-access', methods=['GET'], endpoint='player_access')
@team_login_required
@coach_required
def player_access():
    tid = get_team_id()
    if not tid:
        return redirect(url_for('team_auth'))
    return render_template('team_player_access.html',
                           pending=ident.pending_requests_for_team(tid),
                           rows=ident.access_overview(tid),
                           team=Team.query.get(tid))


@bp.route('/team/player-access/<int:req_id>/approve', methods=['POST'], endpoint='approve_request')
@team_login_required
@coach_required
def approve_request(req_id):
    tid = get_team_id()
    # Fetch UNSCOPED, then authorize against the coach's own team: a forged id
    # from another team resolves to a row we refuse, never to an approval.
    req = PlayerRegistrationRequest.query.get(req_id)
    ok, err = ident.approve(req, tid)
    if not ok:
        flash({'expired': 'Žádost už vypršela.',
               'not_pending': 'Žádost už byla vyřízena.'}.get(err, 'Žádost nebyla nalezena.'), 'error')
        log_event('player_access.approve_denied', team_id=tid, role='coach', level='warning',
                  message='Approval refused', meta={'request_id': req_id, 'reason': err})
        return redirect(url_for('playerauth.player_access'))
    log_event('player_access.approved', team_id=tid, role='coach',
              message='Player access approved',
              meta={'request_id': req.id, 'player_id': req.player_id})
    flash('Přístup byl schválen. Hráč si teď může vytvořit passkey.', 'success')
    return redirect(url_for('playerauth.player_access'))


@bp.route('/team/player-access/<int:req_id>/reject', methods=['POST'], endpoint='reject_request')
@team_login_required
@coach_required
def reject_request(req_id):
    tid = get_team_id()
    req = PlayerRegistrationRequest.query.get(req_id)
    ok, err = ident.reject(req, tid)
    if not ok:
        flash('Žádost nebyla nalezena.', 'error')
        log_event('player_access.reject_denied', team_id=tid, role='coach', level='warning',
                  message='Rejection refused', meta={'request_id': req_id, 'reason': err})
        return redirect(url_for('playerauth.player_access'))
    log_event('player_access.rejected', team_id=tid, role='coach',
              message='Player access rejected',
              meta={'request_id': req.id, 'player_id': req.player_id})
    flash('Žádost byla zamítnuta.', 'info')
    return redirect(url_for('playerauth.player_access'))


@bp.route('/team/player-access/credential/<int:cred_id>/revoke', methods=['POST'],
          endpoint='revoke_credential')
@team_login_required
@coach_required
def revoke_credential(cred_id):
    tid = get_team_id()
    cred = PasskeyCredential.query.get(cred_id)
    ok, err = ident.revoke_credential(cred, tid)
    if not ok:
        flash('Zařízení nebylo nalezeno.', 'error')
        return redirect(url_for('playerauth.player_access'))
    log_event('passkey.revoked', team_id=tid, role='coach',
              message='Passkey revoked', meta={'player_id': cred.player_id, 'credential_pk': cred.id})
    flash('Přístup zařízení byl odebrán.', 'info')
    return redirect(url_for('playerauth.player_access'))


@bp.route('/team/player-access/player/<int:player_id>/revoke', methods=['POST'],
          endpoint='revoke_player')
@team_login_required
@coach_required
def revoke_player(player_id):
    tid = get_team_id()
    player = Player.query.filter_by(id=player_id, team_id=tid).first()
    if not player:
        flash('Hráč nebyl nalezen.', 'error')
        return redirect(url_for('playerauth.player_access'))
    n = ident.revoke_all_for_player(tid, player.id)
    log_event('passkey.revoked_all', team_id=tid, role='coach',
              message='All passkeys revoked for player',
              meta={'player_id': player.id, 'revoked': n})
    flash('Přístup hráče byl odebrán (%d zařízení).' % n, 'info')
    return redirect(url_for('playerauth.player_access'))


# -------------------------------------------------------- passkey: register
@bp.route('/passkey/register/options', methods=['POST'], endpoint='register_options')
@team_login_required
@limiter.limit('20 per hour')
def register_options():
    tid = get_team_id()
    req, err = ident.activation_candidate(tid, session.get(_CLAIM_SESSION_KEY) or '')
    if err:
        return _json_error(err, 403)
    player = Player.query.filter_by(id=req.player_id, team_id=tid).first()
    if not player:
        return _json_error('unknown_player', 404)
    handle = ident.user_handle_for_player(tid, player.id)
    session['onboarding_user_handle'] = handle
    # The OS credential picker needs *something* readable; the roster name is
    # used for that prompt only and is never persisted by CoachHub.
    existing = [c.credential_id for c in PasskeyCredential.query
                .filter_by(team_id=tid, player_id=player.id,
                           status=PasskeyCredential.STATUS_ACTIVE).all()]
    try:
        options = wa.registration_options(user_handle=handle,
                                          display_label=player.name,
                                          exclude_credential_ids=existing)
    except Exception:
        return _json_error('options_failed', 500)
    return jsonify({'ok': True, 'options': json.loads(options)})


@bp.route('/passkey/register/verify', methods=['POST'], endpoint='register_verify')
@team_login_required
@limiter.limit('20 per hour')
def register_verify():
    tid = get_team_id()
    req, err = ident.activation_candidate(tid, session.get(_CLAIM_SESSION_KEY) or '')
    if err:
        return _json_error(err, 403)
    handle = session.get('onboarding_user_handle')
    if not handle:
        return _json_error('challenge_missing', 400)
    payload = request.get_json(silent=True) or {}
    credential = payload.get('credential')
    if not credential:
        return _json_error('malformed_credential', 400)
    try:
        verified = wa.verify_registration(json.dumps(credential))
    except wa.WebAuthnError as exc:
        log_event('passkey.register_failed', team_id=tid, role='player', level='warning',
                  message='Passkey registration failed',
                  meta={'player_id': req.player_id, 'reason': str(exc)})
        return _json_error(str(exc), 400)

    if PasskeyCredential.query.filter_by(credential_id=verified['credential_id']).first():
        return _json_error('credential_exists', 409)

    transports = (credential.get('response') or {}).get('transports') or []
    cred = ident.activate(req, credential=verified, user_handle=handle,
                          transports=[t for t in transports if isinstance(t, str)])
    session.pop('onboarding_user_handle', None)
    session.pop(_CLAIM_SESSION_KEY, None)
    log_event('passkey.registered', team_id=tid, role='player',
              message='Passkey registered', meta={'player_id': cred.player_id})
    # The player is now individually authenticated: fresh session, no leftovers.
    establish_team_session(tid, 'player', auth_method=AUTH_PASSKEY, player_id=cred.player_id)
    return jsonify({'ok': True, 'redirect': url_for('attendance.attendance')})


# ----------------------------------------------------------- passkey: login
@bp.route('/passkey/login/options', methods=['POST'], endpoint='login_options')
@limiter.limit('30 per hour')
def login_options():
    """Public: discoverable-credential login needs no prior session and reveals
    nothing about who exists."""
    try:
        options = wa.authentication_options()
    except Exception:
        return _json_error('options_failed', 500)
    return jsonify({'ok': True, 'options': json.loads(options)})


@bp.route('/passkey/login/verify', methods=['POST'], endpoint='login_verify')
@limiter.limit('30 per hour')
def login_verify():
    payload = request.get_json(silent=True) or {}
    credential = payload.get('credential')
    if not credential:
        return _json_error('malformed_credential', 400)
    raw = json.dumps(credential)
    try:
        cred_id = wa.credential_id_from_response(raw)
    except wa.WebAuthnError:
        return _json_error('malformed_credential', 400)

    # Only ACTIVE credentials resolve: pending and revoked rows are invisible
    # here and therefore can never authenticate.
    cred = ident.lookup_active_credential(cred_id)
    if cred is None:
        wa.clear_challenges()           # burn the challenge on failure too
        log_event('passkey.login_failed', level='warning',
                  message='Unknown, pending or revoked credential')
        return _json_error('unknown_credential', 403)

    try:
        result = wa.verify_authentication(raw, public_key=cred.public_key,
                                          sign_count=cred.sign_count)
    except wa.WebAuthnError as exc:
        log_event('passkey.login_failed', team_id=cred.team_id, level='warning',
                  message='Passkey verification failed',
                  meta={'player_id': cred.player_id, 'reason': str(exc)})
        return _json_error(str(exc), 403)

    # Guard against a cloned authenticator replaying an older counter.
    from datetime import datetime
    cred.sign_count = result['new_sign_count']
    cred.last_used_at = datetime.utcnow()
    db.session.commit()

    establish_team_session(cred.team_id, 'player', auth_method=AUTH_PASSKEY,
                           player_id=cred.player_id)
    log_event('passkey.login_ok', team_id=cred.team_id, role='player',
              message='Passkey login', meta={'player_id': cred.player_id})
    return jsonify({'ok': True, 'redirect': url_for('attendance.attendance')})
