# -*- coding: utf-8 -*-
"""Team calendar feed tokens: lazy creation, lookup and rotation.

The token is a BEARER secret embedded in the feed URL. The public feed route
must resolve it back to a team on every request, so it is stored PLAINTEXT and
looked up directly by an indexed unique column. (A hashed token would force a
full-table scan per request or a separate lookup index; for a low-value,
read-only calendar feed the plaintext bearer token is the standard, simplest
design — the URL is the secret, exactly like an ICS "private address".)

Tokens are NOT team login keys and never touch TeamKey.
"""
import secrets
from datetime import datetime

from coach.extensions import db
from coach.models import TeamCalendarFeedToken

# 32 url-safe bytes = 256 bits of entropy (well above the 128-bit floor).
_TOKEN_BYTES = 32
_PREFIX = 'chhcal_'


def gen_feed_token():
    return _PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)


def _unique_token(max_attempts=6):
    """A token that collides with no existing (active or inactive) token."""
    for _ in range(max_attempts):
        candidate = gen_feed_token()
        exists = TeamCalendarFeedToken.query.filter_by(token=candidate).first()
        if not exists:
            return candidate
    return None  # ~256-bit space: unreachable in practice; caller must handle None


def get_active_token(team_id):
    return (TeamCalendarFeedToken.query
            .filter_by(team_id=team_id, active=True)
            .order_by(TeamCalendarFeedToken.created_at.desc())
            .first())


def get_or_create_active_token(team_id):
    """Return the team's active feed token, creating one lazily if absent."""
    existing = get_active_token(team_id)
    if existing:
        return existing
    token = _unique_token()
    if not token:
        return None
    row = TeamCalendarFeedToken(team_id=team_id, token=token, active=True)
    db.session.add(row)
    db.session.commit()
    return row


def rotate_token(team_id):
    """Deactivate the current active token(s) and create a fresh active one.

    Returns the new token row, or None if a unique token could not be generated
    (in which case nothing is changed — fail closed, old token stays valid)."""
    new_token = _unique_token()
    if not new_token:
        return None
    now = datetime.utcnow()
    (TeamCalendarFeedToken.query
     .filter_by(team_id=team_id, active=True)
     .update({TeamCalendarFeedToken.active: False,
              TeamCalendarFeedToken.rotated_at: now}))
    row = TeamCalendarFeedToken(team_id=team_id, token=new_token, active=True)
    db.session.add(row)
    db.session.commit()
    return row


def team_for_token(token):
    """Resolve an ACTIVE token to its team_id, or None. Never reveals whether a
    team exists for an invalid/rotated token (caller returns a plain 404)."""
    if not token:
        return None
    row = TeamCalendarFeedToken.query.filter_by(token=token, active=True).first()
    return row.team_id if row else None
