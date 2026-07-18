from flask import g, redirect
import secrets

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
        # Team-only gate: allow team session; otherwise only static/legal/team auth pages
        from flask import request, session
        # Allow active team session
        if session.get('team_login') and session.get('team_id'):
            return
        # Allow public paths (path-based to avoid endpoint resolution issues)
        p = request.path or '/'
        if p.startswith('/static/'):
            return
        if p.startswith('/owner'):
            return
        # Public team calendar feed: the URL token is the bearer secret, so the
        # feed must be reachable without a team session. The route itself 404s on
        # an invalid/rotated token, so this exposes no cross-team data.
        if p.startswith('/calendar/team/'):
            return
        if p in ('/', '/favicon.ico', '/sw.js', '/team/auth', '/team/login', '/team/create', '/terms', '/privacy', '/about'):
            return
        # Everything else goes to team auth
        return redirect('/team/auth')
