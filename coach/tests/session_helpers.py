"""Shared test helpers for establishing team sessions.

One source of truth for what a session looks like under the player identity
model, so individual test files do not each re-encode it:

    coach            team_key, no player_id                 -> full coach app
    verified player  passkey  + player_id                   -> full player app
    shared key       team_key, no player_id                  -> ONBOARDING ONLY

The last one is deliberately NOT a normal in-app session: `security.require_approval`
bounces it to /player/onboarding. Tests that want "a player using the app" want
`login_session(..., 'player')`; tests about the shared key itself want
`login_shared_key_session`.
"""


def _first_player_id(team_id):
    from coach.models import Player
    p = Player.query.filter_by(team_id=team_id).order_by(Player.id.asc()).first()
    return p.id if p else 1


def login_session(client, team_id, role, player_id=None):
    """Log a client in as a coach or as a passkey-VERIFIED player."""
    with client.session_transaction() as s:
        s['team_id'] = team_id
        s['team_role'] = role
        s['team_login'] = True
        if role == 'player':
            s['auth_method'] = 'passkey'
            s['player_id'] = player_id or _first_player_id(team_id)
        else:
            s['auth_method'] = 'team_key'
            s.pop('player_id', None)


def login_shared_key_session(client, team_id):
    """Onboarding-only session: the team is proven, the person is not."""
    with client.session_transaction() as s:
        s['team_id'] = team_id
        s['team_role'] = 'player'
        s['team_login'] = True
        s['auth_method'] = 'team_key'
        s.pop('player_id', None)
