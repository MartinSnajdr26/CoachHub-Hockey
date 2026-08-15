from flask import g, redirect
import secrets

# Paths reachable with no team session at all (public, legal, asset, ceremony).
PUBLIC_PATHS = frozenset({
    '/', '/favicon.ico', '/sw.js',
    '/team/auth', '/team/login', '/team/create',
    '/terms', '/privacy', '/about',
    # Passkey login is how a returning player signs in, so it must work with no
    # session. Both are pure WebAuthn ceremony steps: they read no team data and
    # only ever succeed against an ACTIVE stored credential.
    '/passkey/login/options', '/passkey/login/verify',
})
PUBLIC_PREFIXES = ('/static/', '/owner',
                   # Public team calendar feed: the URL token is the bearer
                   # secret and the route 404s on an invalid/rotated token.
                   '/calendar/team/')

# The ONLY paths a shared-key (onboarding-only) player session may reach. This
# is the whole point of the shared key: identify the team, complete onboarding,
# nothing else. `/player/onboarding` is itself allowed, so the redirect below
# can never loop.
ONBOARDING_PATHS = frozenset({
    '/player/onboarding',
    '/player/onboarding/claim',
    '/player/onboarding/cancel',
    # Needed after coach approval to actually create the credential.
    '/passkey/register/options',
    '/passkey/register/verify',
    '/team/logout',
})

ONBOARDING_REDIRECT = '/player/onboarding'


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


def register_security(app):
    """Register security-related hooks: CSP nonce, headers, and approval gate."""

    @app.before_request
    def _set_csp_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.context_processor
    def _inject_csp_nonce():
        return {'csp_nonce': getattr(g, 'csp_nonce', '')}

    @app.after_request
    def set_security_headers(resp):
        is_dev = bool(app.config.get('IS_DEV'))
        # HSTS (only meaningful over HTTPS)
        if not is_dev:
            resp.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains; preload')
        else:
            resp.headers.setdefault('Strict-Transport-Security', 'max-age=0')
        # Basic hardening
        resp.headers.setdefault('X-Frame-Options', 'DENY')
        resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
        resp.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        resp.headers.setdefault('Permissions-Policy', "geolocation=(), microphone=(), camera=(), payment=()")
        # CSP – nonce-based, allow inline only in dev to avoid breakage until all templates are refactored
        script_src = ["'self'", f"'nonce-{getattr(g, 'csp_nonce', '')}'"]
        if is_dev:
            script_src.append("'unsafe-inline'")
        csp = (
            "default-src 'self'; "
            "img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            f"script-src {' '.join(script_src)}"
        )
        resp.headers.setdefault('Content-Security-Policy', csp)
        # Never let the browser serve a stale HTML document. Static assets are
        # cache-busted separately (?v=) and stay cacheable; only dynamic pages get
        # no-store, so an old page (e.g. missing newer inline JS) can't be replayed
        # from cache.
        ctype = resp.headers.get('Content-Type', '')
        if 'text/html' in ctype:
            resp.headers['Cache-Control'] = 'no-store, must-revalidate'
        return resp

    @app.before_request
    def require_approval():
        """Two gates, in order.

        1. No team session -> only public paths; everything else to /team/auth.
        2. A team session that proves a TEAM but no PERSON (the shared player
           key) -> only the onboarding paths; everything else to
           /player/onboarding. Typing a URL therefore cannot skip onboarding,
           which UI-level hiding alone would not prevent.

        Coaches and passkey-verified players are unaffected by gate 2.
        """
        from flask import request, session
        # Path-based (not endpoint-based) to avoid endpoint-resolution issues.
        p = request.path or '/'
        if is_public_path(p):
            return
        if session.get('team_login') and session.get('team_id'):
            from coach.auth_utils import is_onboarding_only_session
            if is_onboarding_only_session() and p not in ONBOARDING_PATHS:
                return redirect(ONBOARDING_REDIRECT)
            return
        # Everything else goes to team auth
        return redirect('/team/auth')
