from flask import g, redirect, url_for
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
        if p in ('/', '/favicon.ico', '/team/auth', '/team/login', '/team/create', '/terms', '/privacy', '/about'):
            return
        # Everything else goes to team auth
        return redirect('/team/auth')
