from functools import wraps
from flask import session, redirect, url_for, request, flash
from flask_login import current_user

# ---------------------------------------------------------------------------
# Session identity model (team-only mode)
#
#   team_id      the team this session may touch
#   team_role    'coach' | 'player'
#   team_login   True once a key/passkey ceremony succeeded
#   auth_method  'team_key'  -> a SHARED key was used. Team-level access only.
#                'passkey'   -> an individual WebAuthn credential was verified.
#   player_id    the opaque individual identity. Set ONLY by AUTH_PASSKEY.
#
# A shared player key deliberately never yields `player_id`: it proves "I can
# reach this team's onboarding", not "I am player 145".
# ---------------------------------------------------------------------------
AUTH_TEAM_KEY = 'team_key'
AUTH_PASSKEY = 'passkey'

# Every identity-bearing key. Cleared as a set on login and logout so a previous
# coach / player A / player B session can never leak into the next one.
_IDENTITY_SESSION_KEYS = (
    'team_id', 'team_role', 'team_login', 'auth_method', 'player_id',
    'onboarding_claim_token', 'webauthn_reg_challenge', 'webauthn_auth_challenge',
)


def reset_identity_session() -> None:
    """Drop every identity key, preserving only the unrelated owner-admin gate.

    Called before establishing a session and on logout, so no stale `player_id`,
    role or team survives a re-login as somebody else.
    """
    owner = session.get('owner_admin')
    session.clear()
    if owner:
        session['owner_admin'] = owner


def establish_team_session(team_id: int, role: str, *, auth_method: str,
                           player_id: int | None = None) -> None:
    """Start a clean authenticated session. Always resets first."""
    reset_identity_session()
    session.permanent = True
    session['team_id'] = int(team_id)
    session['team_role'] = role
    session['team_login'] = True
    session['auth_method'] = auth_method
    if player_id is not None and auth_method == AUTH_PASSKEY:
        session['player_id'] = int(player_id)


def get_auth_method() -> str:
    return session.get('auth_method') or AUTH_TEAM_KEY


def get_player_id() -> int | None:
    """The authenticated individual player, or None.

    Returns a value ONLY for a passkey-verified player session. A shared-key
    session always returns None no matter what it posts, which is what stops
    "player key -> pick a name -> act as that player".
    """
    if session.get('auth_method') != AUTH_PASSKEY:
        return None
    if (session.get('team_role') or 'player') != 'player':
        return None
    pid = session.get('player_id')
    try:
        return int(pid) if pid else None
    except (TypeError, ValueError):
        return None


def is_verified_player() -> bool:
    return get_player_id() is not None


def is_onboarding_only_session() -> bool:
    """True for a session that proves a TEAM but no individual player.

    That is the shared player key: `team_role='player'` with no verified
    `player_id`. Such a session may only complete onboarding — it is NOT
    equivalent to a passkey-verified player and must not reach normal player
    functionality. This is the single source of truth for that distinction;
    the global gate in `security.require_approval`, the post-login redirect and
    the navigation all read it rather than re-deriving the condition.

    Sessions predating `auth_method` fall through `get_auth_method()`'s
    `team_key` default and are correctly treated as onboarding-only, which is
    the intended migration path for players already using the shared key.

    Coaches are never onboarding-only.
    """
    if not (session.get('team_login') and session.get('team_id')):
        return False
    if (session.get('team_role') or 'player') != 'player':
        return False
    return get_player_id() is None


def get_team_id() -> int | None:
    tid = session.get('team_id')
    if tid:
        try:
            return int(tid)
        except Exception:
            return None
    try:
        if current_user.is_authenticated and getattr(current_user, 'team_id', None):
            return int(current_user.team_id)
    except Exception:
        pass
    return None


def get_team_role() -> str:
    r = session.get('team_role')
    if r:
        return r
    try:
        if current_user.is_authenticated:
            return getattr(current_user, 'role', 'player') or 'player'
    except Exception:
        pass
    return 'player'


def team_login_required(fn):
    @wraps(fn)
    def _wrap(*args, **kwargs):
        if session.get('team_login') and session.get('team_id'):
            return fn(*args, **kwargs)
        if getattr(current_user, 'is_authenticated', False):
            return fn(*args, **kwargs)
        return redirect('/team/auth')
    return _wrap


def coach_required(fn):
    @wraps(fn)
    def _wrap(*args, **kwargs):
        role = get_team_role()
        if role == 'coach':
            return fn(*args, **kwargs)
        flash('Tuto akci může provést pouze trenér.', 'error')
        ref = request.referrer or url_for('home')
        return redirect(ref)
    return _wrap


def verified_player_required(fn):
    """Gate an action on an individually authenticated (passkey) player.

    A shared-player-key session is rejected: it has no proven individual
    identity, so it must not perform per-player mutations.
    """
    @wraps(fn)
    def _wrap(*args, **kwargs):
        if is_verified_player():
            return fn(*args, **kwargs)
        flash('Tuto akci může provést jen ověřený hráč přihlášený přes passkey.', 'error')
        return redirect(url_for('playerauth.onboarding'))
    return _wrap

