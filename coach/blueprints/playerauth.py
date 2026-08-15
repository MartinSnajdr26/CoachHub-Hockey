"""Player identity: onboarding claim, coach approval, passkey register/login.

Design choice (see report): the coach approves BEFORE any credential exists.
The claim is bound to the requesting browser by a random token stored only as a
sha256 hash, so an approved claim can be completed by that browser alone —
holding the shared player key is not enough.

That token lives in a persistent HttpOnly cookie (services/onboarding_resume),
NOT in the Flask session, so the player may close the app while waiting for the
coach and still finish later on the same browser. The cookie authorises exactly
one thing: continuing that one request. It never becomes a session identity —
see `security.require_approval`, which still gates every app path.
"""
import json

from flask import (Blueprint, jsonify, make_response, redirect, render_template,
                   request, session, url_for, flash)

from coach.auth_utils import (AUTH_PASSKEY, coach_required, establish_team_session,
                              get_auth_method, get_player_id, get_team_id,
                              get_team_role, team_login_required)
from coach.extensions import db, limiter
from coach.models import PasskeyCredential, Player, PlayerRegistrationRequest, Team
from coach.services import onboarding_resume as resume
from coach.services import player_identity as ident
from coach.services import webauthn_svc as wa
from coach.services.logging import log_event

bp = Blueprint('playerauth', __name__)


def _json_error(code: str, status: int = 400):
    return jsonify({'ok': False, 'error': code}), status


# --------------------------------------------------------------- onboarding
@bp.route('/player/onboarding', methods=['GET'], endpoint='onboarding')
def onboarding():
    """Claim state for this browser, in either of two modes.

    * With a shared-key team session — the full screen, including the roster
      picker, exactly as before.
    * With NO session but a valid resume cookie — a resume-only screen showing
      just this request's state. The roster is deliberately NOT loaded there:
      the cookie proves ownership of one request, it is not a substitute for the
      shared player key and must not expose the team's roster or let the holder
      claim a different player.
    """
    tid = get_team_id()
    if tid and get_team_role() == 'coach':
        # Coaches manage access instead of claiming an identity.
        return redirect(url_for('playerauth.player_access'))

    token = resume.read_token()
    resumable, _reason = resume.resolve_resume_request(token)

    if not tid:
        # Session-less return visit: the cookie is the only thing that can bring
        # this browser back in. Anything dead (unknown / expired / terminal)
        # falls through to normal login and the stale cookie is dropped.
        if resumable is None:
            resp = make_response(redirect(url_for('teamauth.team_auth')))
            return resume.clear(resp) if token else resp
        player = Player.query.filter_by(id=resumable.player_id,
                                        team_id=resumable.team_id).first()
        return render_template(
            'player_onboarding.html',
            players=[], players_with_access=set(),
            state=resumable.status, req=resumable, claimed_player=player,
            already_verified=None, resume_only=True,
            secure_context=wa.is_secure_context(),
        )

    # Shared-key session: same screen as before.
    req = ident.find_by_token(token)
    state, claimed_player = 'none', None
    if req is not None and req.team_id == tid:
        claimed_player = Player.query.filter_by(id=req.player_id, team_id=tid).first()
        if ident.is_expired(req) and req.status in (PlayerRegistrationRequest.STATUS_PENDING,
                                                    PlayerRegistrationRequest.STATUS_APPROVED):
            state = 'expired'
        else:
            state = req.status
    else:
        req = None

    players = Player.query.filter_by(team_id=tid).order_by(Player.name.asc()).all()
    taken = {p.id for p in players if ident.player_has_active_access(tid, p.id)}
    resp = make_response(render_template(
        'player_onboarding.html',
        players=players, state=state, req=req, claimed_player=claimed_player,
        players_with_access=taken,
        already_verified=get_player_id(), resume_only=False,
        secure_context=wa.is_secure_context(),
    ))
    if resumable is not None and not resume.read_cookie_token():
        # Claim created before the resume cookie existed (token still in the
        # session): adopt it now so this browser survives the session going away.
        resume.attach(resp, token)
    elif token and resumable is None:
        # A cookie that no longer resolves to anything live is dead weight; drop
        # it so a later session-less visit is not misled by it.
        resume.clear(resp)
    return resp


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

    # A FRESH token per claim: one hash therefore maps to exactly one request,
    # and the browser can never end up holding two resumable claims. The old
    # cookie (if any) is passed in only so its live claim can be superseded.
    token = ident.new_claim_token()
    req, err = ident.create_request(tid, player_id, token,
                                    prior_token=resume.read_token())
    if err:
        flash('Tento hráč nebyl v týmu nalezen.', 'error')
        return redirect(url_for('playerauth.onboarding'))
    # Audit the lifecycle by opaque ids only — never the claimed name, and never
    # the token itself.
    log_event('player_access.requested', team_id=tid, role='player',
              message='Player access requested',
              meta={'request_id': req.id, 'player_id': req.player_id})
    flash('Žádost byla odeslána. Počkej, až ji trenér schválí.', 'success')
    resp = make_response(redirect(url_for('playerauth.onboarding')))
    return resume.attach(resp, token)


@bp.route('/player/onboarding/cancel', methods=['POST'], endpoint='onboarding_cancel')
def onboarding_cancel():
    """Withdraw this browser's own claim.

    Works with or without a team session, because a player who returned via the
    resume cookie must be able to cancel too. The request is resolved from the
    cookie alone and its own team_id is used for the transition, so this can
    only ever cancel the claim this browser actually owns.
    """
    req, _reason = resume.resolve_resume_request()
    if req is not None:
        ident.reject(req, req.team_id)
        log_event('player_access.cancelled', team_id=req.team_id, role='player',
                  message='Player withdrew access request',
                  meta={'request_id': req.id, 'player_id': req.player_id})
    flash('Žádost byla zrušena.', 'info')
    # Terminal for this token: cancelling must also make the cookie useless.
    target = ('playerauth.onboarding' if get_team_id() else 'teamauth.team_auth')
    return resume.clear(make_response(redirect(url_for(target))))


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
@limiter.limit('20 per hour')
def register_options():
    """Registration options for the request THIS browser owns.

    No team session is required: the resume cookie is the proof, and the
    resolved row — never a session or a posted field — supplies team_id and
    player_id. An unapproved, expired or terminal request yields 403 here, so a
    credential can never be minted ahead of coach approval.
    """
    req, err = ident.activation_candidate_by_token(resume.read_token())
    if err:
        return _json_error(err, 403)
    tid = req.team_id
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
@limiter.limit('20 per hour')
def register_verify():
    req, err = ident.activation_candidate_by_token(resume.read_token())
    if err:
        return _json_error(err, 403)
    tid = req.team_id
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
    log_event('passkey.registered', team_id=tid, role='player',
              message='Passkey registered', meta={'player_id': cred.player_id})
    # The player is now individually authenticated: fresh session, no leftovers.
    establish_team_session(tid, 'player', auth_method=AUTH_PASSKEY, player_id=cred.player_id)
    # The claim is ACTIVATED, so the token no longer resolves to anything
    # resumable server-side; delete the cookie too so nothing stale is replayed
    # or left sitting in the browser.
    resp = make_response(jsonify({'ok': True, 'redirect': url_for('attendance.attendance')}))
    return resume.clear(resp)


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
