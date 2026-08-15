"""Resumable onboarding: the browser-bound claim token as a persistent cookie.

Why this exists
---------------
The claim token proving "this browser created that registration request" used to
live in the Flask *session*. A session is cleared by logout, by expiry, and by
`reset_identity_session()`, so a player who closed the app before the coach got
round to approving could not safely finish: the approved request was still in
the database, but nothing in the browser could prove ownership of it any more.

The token now rides in its own long-lived HttpOnly cookie, decoupled from the
session, so the browser may be closed and reopened. The DATABASE side is
unchanged: still only `sha256(token)` in `PlayerRegistrationRequest.
claim_token_hash`. No new column, no migration.

What the token is NOT
--------------------
It is not authentication. It identifies *the browser that initiated one specific
registration request* and authorises exactly one thing: continuing that request.
It never establishes `player_id` as a session identity, never grants the shared
player key's roster access, and cannot reach the app — `security.require_approval`
still gates everything, and this module deliberately never touches `session`.

Identity is always read from the resolved row (team_id, player_id, status),
never from anything the client sends.
"""
from flask import current_app, request

from coach.models import PlayerRegistrationRequest
from coach.services import player_identity as ident

# Host-only cookie (no Domain attribute) so it is never shared with a sibling
# host. Path '/' because it must be readable both by /player/onboarding and by
# the entry points (/ and /team/auth) that offer to resume.
COOKIE_PATH = '/'
DEFAULT_COOKIE_NAME = 'chh_onboarding'

# Terminal/invalid outcomes. The caller clears the cookie on any of these so a
# dead token never lingers in the browser.
REASON_NONE = 'no_token'
REASON_NOT_FOUND = 'not_found'
REASON_EXPIRED = 'expired'
REASON_TERMINAL = 'terminal'

RESUMABLE_STATUSES = (PlayerRegistrationRequest.STATUS_PENDING,
                      PlayerRegistrationRequest.STATUS_APPROVED)


def cookie_name() -> str:
    return current_app.config.get('PLAYER_ONBOARDING_COOKIE_NAME') or DEFAULT_COOKIE_NAME


def cookie_max_age() -> int:
    """Seconds. Aligned with the request lifetime so the cookie cannot outlive
    every request it could possibly unlock."""
    return int(current_app.config.get('PLAYER_ONBOARDING_COOKIE_MAX_AGE') or 0)


def _secure() -> bool:
    """Mirror the session cookie's policy: secure everywhere except dev, so
    local http testing works without weakening production."""
    return bool(current_app.config.get('SESSION_COOKIE_SECURE'))


# Where the token used to live. Read-only fallback so claims already in flight
# when this ships are not stranded: the next onboarding page view adopts the
# session token into a cookie (see playerauth.onboarding) and from then on the
# cookie is the only source. Nothing ever writes this key any more.
LEGACY_SESSION_KEY = 'onboarding_claim_token'


def read_cookie_token() -> str:
    return request.cookies.get(cookie_name()) or ''


def read_token() -> str:
    """The claim token for this browser: the cookie, else the legacy session."""
    from flask import session
    return read_cookie_token() or session.get(LEGACY_SESSION_KEY) or ''


def attach(response, token: str):
    """Set the resume cookie on `response`. HttpOnly + SameSite=Lax + host-only.

    Lax (not Strict) because the player often arrives by following a link or
    reopening the app; the cookie is only ever read by same-site GETs and
    never authorises a state change on its own.
    """
    response.set_cookie(
        cookie_name(), token,
        max_age=cookie_max_age(),
        httponly=True,                 # JavaScript must never see it
        secure=_secure(),
        samesite='Lax',
        path=COOKIE_PATH,
        # no domain= -> host-only cookie
    )
    return response


def clear(response):
    """Delete the resume cookie. Must use the same path, or the browser keeps it."""
    response.delete_cookie(cookie_name(), path=COOKIE_PATH)
    return response


def resolve_resume_request(token: str | None = None):
    """(request, reason) for the claim this browser may continue.

    Resolution is by token hash ALONE — the row then supplies team_id and
    player_id. Nothing from the client (form field, query string, or another
    cookie) influences which request is returned, so a forged player_id or
    team_id cannot redirect the activation to somebody else.

    Returns (None, reason) for a missing, unknown, expired, or already-terminal
    (activated / rejected / cancelled) token; callers clear the cookie then, so
    replay after activation, rejection, expiry or cancellation all dead-end here.
    """
    token = read_token() if token is None else token
    if not token:
        return None, REASON_NONE
    req = ident.find_by_token(token)
    if req is None:
        return None, REASON_NOT_FOUND
    if req.status not in RESUMABLE_STATUSES:
        return None, REASON_TERMINAL
    if ident.is_expired(req):
        return None, REASON_EXPIRED
    return req, None


def has_resumable_claim() -> bool:
    """Cheap 'should the entry pages offer to resume?' check."""
    req, _ = resolve_resume_request()
    return req is not None
