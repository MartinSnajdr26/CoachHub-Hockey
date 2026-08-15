"""Lifecycle of a player's claim on a roster identity.

Flow enforced here:

    shared player key   ->  team-level onboarding access only
    pick a roster entry ->  PENDING request (grants nothing)
    coach of THAT team  ->  approve / reject
    approved + same browser -> passkey created, request ACTIVATED
    activation          ->  claimed_name wiped, only opaque player_id remains

Every state transition is validated server-side against the acting session's
team, so a forged request id can never cross a team boundary.
"""
import hashlib
import secrets
from datetime import datetime, timedelta

from coach.extensions import db
from coach.models import PasskeyCredential, Player, PlayerRegistrationRequest

# A claim must be acted on reasonably soon: long enough for a coach to notice at
# the next training, short enough that abandoned claims do not linger.
PENDING_TTL_DAYS = 7
# After approval the player gets a fresh window to actually create the passkey.
ACTIVATION_TTL_DAYS = 7


# ------------------------------------------------------------ claim tokens
def new_claim_token() -> str:
    """Random bearer token proving 'this browser created that request'."""
    return secrets.token_urlsafe(32)


def hash_claim_token(token: str) -> str:
    return hashlib.sha256((token or '').encode('utf-8')).hexdigest()


# ----------------------------------------------------------------- queries
def _now() -> datetime:
    return datetime.utcnow()


def is_expired(req: PlayerRegistrationRequest, now: datetime | None = None) -> bool:
    now = now or _now()
    return bool(req.expires_at and req.expires_at <= now)


def active_credentials_for_player(team_id: int, player_id: int):
    return (PasskeyCredential.query
            .filter_by(team_id=team_id, player_id=player_id,
                       status=PasskeyCredential.STATUS_ACTIVE)
            .order_by(PasskeyCredential.created_at.asc()).all())


def player_has_active_access(team_id: int, player_id: int) -> bool:
    return bool(active_credentials_for_player(team_id, player_id))


def pending_requests_for_team(team_id: int):
    """Coach inbox: live pending claims only (expired ones are never shown as
    actionable, so a coach cannot approve something already stale)."""
    now = _now()
    return (PlayerRegistrationRequest.query
            .filter(PlayerRegistrationRequest.team_id == team_id,
                    PlayerRegistrationRequest.status == PlayerRegistrationRequest.STATUS_PENDING,
                    PlayerRegistrationRequest.expires_at > now)
            .order_by(PlayerRegistrationRequest.created_at.asc()).all())


def find_by_claim_token(team_id: int, token: str):
    """Resolve the request belonging to THIS browser, scoped to THIS team."""
    if not token or not team_id:
        return None
    return (PlayerRegistrationRequest.query
            .filter_by(team_id=team_id, claim_token_hash=hash_claim_token(token))
            .order_by(PlayerRegistrationRequest.created_at.desc()).first())


def find_by_token(token: str):
    """Resolve a claim from the token ALONE — no team_id needed.

    This is what makes onboarding resumable after the session is gone: a
    returning browser has only its cookie, so team_id cannot come from a
    session. The token carries 256 bits of entropy from `secrets`, so the hash
    identifies one row on its own; the ROW then supplies team_id and player_id
    and the caller must use those rather than anything the client sent.
    """
    if not token:
        return None
    return (PlayerRegistrationRequest.query
            .filter_by(claim_token_hash=hash_claim_token(token))
            .order_by(PlayerRegistrationRequest.created_at.desc()).first())


def activation_candidate_by_token(token: str):
    """The request this browser may create a passkey for, resolved from the
    token alone. Team scoping is implied by the row, never asserted by caller."""
    req = find_by_token(token)
    if req is None:
        return None, 'not_found'
    if req.status != PlayerRegistrationRequest.STATUS_APPROVED:
        return None, 'not_approved'
    if is_expired(req):
        return None, 'expired'
    return req, None


# ------------------------------------------------------------- transitions
def create_request(team_id: int, player_id: int, token: str, prior_token: str = None):
    """Create a PENDING claim bound to `token`. Returns (request, error_code).

    The player must belong to the onboarding team — a posted player_id from
    another team is refused here, not merely hidden in the UI.

    `token` is always FRESH: each claim mints its own token so one hash maps to
    exactly one row and a browser can never hold two resumable claims. Any live
    claim still held under `prior_token` (the browser's previous resume cookie)
    is superseded first, so a user who changes their mind does not leave two
    competing pending rows for the coach to guess at. Superseding is deliberately
    not team-scoped: the browser gets one claim, whichever team it was for.
    """
    player = Player.query.filter_by(id=player_id, team_id=team_id).first()
    if not player:
        return None, 'unknown_player'

    now = _now()
    prior = find_by_token(prior_token) if prior_token else None
    if prior is not None and prior.status in (PlayerRegistrationRequest.STATUS_PENDING,
                                              PlayerRegistrationRequest.STATUS_APPROVED):
        prior.status = PlayerRegistrationRequest.STATUS_REJECTED
        prior.rejected_at = now
        prior.claimed_name = None

    req = PlayerRegistrationRequest(
        team_id=team_id,
        player_id=player.id,
        claimed_name=player.name[:100],       # temporary: for the coach's decision only
        status=PlayerRegistrationRequest.STATUS_PENDING,
        claim_token_hash=hash_claim_token(token),
        created_at=now,
        expires_at=now + timedelta(days=PENDING_TTL_DAYS),
    )
    db.session.add(req)
    db.session.commit()
    return req, None


def approve(req: PlayerRegistrationRequest, team_id: int):
    """Coach approval. Returns (ok, error_code).

    `team_id` is the AUTHENTICATED coach's team; a request from another team is
    refused even if its id was guessed correctly.
    """
    if req is None or req.team_id != team_id:
        return False, 'not_found'
    if req.status != PlayerRegistrationRequest.STATUS_PENDING:
        return False, 'not_pending'
    if is_expired(req):
        return False, 'expired'
    now = _now()
    req.status = PlayerRegistrationRequest.STATUS_APPROVED
    req.approved_at = now
    # Fresh window for the player to complete the passkey ceremony.
    req.expires_at = now + timedelta(days=ACTIVATION_TTL_DAYS)
    db.session.commit()
    return True, None


def reject(req: PlayerRegistrationRequest, team_id: int):
    """Coach rejection. Terminal: the temporary name is wiped immediately and the
    request can never be approved or activated afterwards."""
    if req is None or req.team_id != team_id:
        return False, 'not_found'
    if req.status in (PlayerRegistrationRequest.STATUS_REJECTED,
                      PlayerRegistrationRequest.STATUS_ACTIVATED):
        return False, 'not_pending'
    req.status = PlayerRegistrationRequest.STATUS_REJECTED
    req.rejected_at = _now()
    req.claimed_name = None
    db.session.commit()
    return True, None


def activation_candidate(team_id: int, token: str):
    """The request this browser may complete a passkey for, or (None, error)."""
    req = find_by_claim_token(team_id, token)
    if req is None:
        return None, 'not_found'
    if req.status != PlayerRegistrationRequest.STATUS_APPROVED:
        return None, 'not_approved'
    if is_expired(req):
        return None, 'expired'
    return req, None


def user_handle_for_player(team_id: int, player_id: int) -> str:
    """Reuse the player's existing opaque handle so extra devices land on the
    same WebAuthn user account; mint a fresh random one for a first credential."""
    from coach.services import webauthn_svc
    existing = (PasskeyCredential.query
                .filter_by(team_id=team_id, player_id=player_id)
                .order_by(PasskeyCredential.created_at.asc()).first())
    if existing and existing.user_handle:
        return existing.user_handle
    return webauthn_svc.new_user_handle()


def activate(req: PlayerRegistrationRequest, *, credential: dict, user_handle: str,
             transports=None):
    """Persist the verified credential and finish the request.

    This is the point where the temporary identifying data is destroyed: the
    claimed name is dropped and only (team_id, player_id, credential) remains.
    """
    now = _now()
    cred = PasskeyCredential(
        team_id=req.team_id,
        player_id=req.player_id,
        role='player',
        credential_id=credential['credential_id'],
        public_key=credential['public_key'],
        sign_count=credential.get('sign_count') or 0,
        user_handle=user_handle,
        transports=(','.join(transports)[:120] if transports else None),
        device_type=(credential.get('device_type') or None),
        backed_up=bool(credential.get('backed_up')),
        status=PasskeyCredential.STATUS_ACTIVE,
        created_at=now,
    )
    db.session.add(cred)
    req.status = PlayerRegistrationRequest.STATUS_ACTIVATED
    req.activated_at = now
    req.claimed_name = None          # temporary identifying data removed here
    db.session.commit()
    return cred


def revoke_credential(cred: PasskeyCredential, team_id: int):
    """Revoke one device. Soft state change — the row survives for audit and can
    never authenticate again."""
    if cred is None or cred.team_id != team_id:
        return False, 'not_found'
    if cred.status == PasskeyCredential.STATUS_REVOKED:
        return False, 'already_revoked'
    cred.status = PasskeyCredential.STATUS_REVOKED
    cred.revoked_at = _now()
    db.session.commit()
    return True, None


def revoke_all_for_player(team_id: int, player_id: int) -> int:
    """Revoke every device of one player (lost phone / player left)."""
    now = _now()
    creds = active_credentials_for_player(team_id, player_id)
    for c in creds:
        c.status = PasskeyCredential.STATUS_REVOKED
        c.revoked_at = now
    # Any live claim for that player becomes meaningless too.
    for req in (PlayerRegistrationRequest.query
                .filter(PlayerRegistrationRequest.team_id == team_id,
                        PlayerRegistrationRequest.player_id == player_id,
                        PlayerRegistrationRequest.status.in_([
                            PlayerRegistrationRequest.STATUS_PENDING,
                            PlayerRegistrationRequest.STATUS_APPROVED]))
                .all()):
        req.status = PlayerRegistrationRequest.STATUS_REJECTED
        req.rejected_at = now
        req.claimed_name = None
    db.session.commit()
    return len(creds)


def lookup_active_credential(credential_id: str):
    """Authentication-time lookup. Only ACTIVE credentials are returned, so a
    pending or revoked row can never produce a session."""
    if not credential_id:
        return None
    return (PasskeyCredential.query
            .filter_by(credential_id=credential_id,
                       status=PasskeyCredential.STATUS_ACTIVE).first())


def access_overview(team_id: int):
    """Per-player access rows for the coach UI. No credential ids, no public
    keys — a coach sees only 'active / how many devices'."""
    players = Player.query.filter_by(team_id=team_id).order_by(Player.name.asc()).all()
    creds = (PasskeyCredential.query
             .filter_by(team_id=team_id, status=PasskeyCredential.STATUS_ACTIVE).all())
    by_player = {}
    for c in creds:
        by_player.setdefault(c.player_id, []).append(c)
    rows = []
    for p in players:
        devices = by_player.get(p.id, [])
        rows.append({
            'player': p,
            'device_count': len(devices),
            'is_active': bool(devices),
            'devices': devices,
            'last_used_at': max((d.last_used_at for d in devices if d.last_used_at), default=None),
        })
    return rows
