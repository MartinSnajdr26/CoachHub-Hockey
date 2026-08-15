"""WebAuthn / passkey plumbing for CoachHub player identity.

All cryptography is delegated to `py_webauthn` (the `webauthn` package) — none of
it is reimplemented here. This module only:

- resolves the Relying Party (RP) id / origin from config,
- mints and consumes single-use challenges,
- serialises the two ceremonies to plain JSON-able dicts for the browser,
- verifies the browser's responses and reports the outcome.

Challenges live in the Flask session (a signed, tamper-proof cookie), carry an
absolute expiry, and are POPPED on use, so a captured response cannot be replayed
against a second ceremony.
"""
import base64
import os
import secrets
from datetime import datetime, timedelta

from flask import current_app, request, session

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

# Ceremonies are short-lived: enough for a fingerprint/FaceID prompt, not enough
# to be parked and replayed later.
CHALLENGE_TTL_SECONDS = 300

_REG_CHALLENGE_KEY = 'webauthn_reg_challenge'
_AUTH_CHALLENGE_KEY = 'webauthn_auth_challenge'


class WebAuthnError(Exception):
    """Ceremony could not be completed (bad challenge, failed verification…)."""


# --------------------------------------------------------------- RP config
def _strip_port(host: str) -> str:
    return (host or '').split(':')[0]


def rp_id() -> str:
    """The RP ID (an effective domain — never a URL, never a port).

    Explicit config wins. Otherwise it is derived from the request host, which
    is what a single-domain deployment wants and what makes localhost work
    without loosening anything: the browser independently refuses to create or
    use a credential whose rpId does not match the page's own origin, so a
    spoofed Host header cannot produce a credential for another domain.
    """
    configured = (current_app.config.get('WEBAUTHN_RP_ID') or '').strip()
    if configured:
        return configured
    return _strip_port(request.host) or 'localhost'


def rp_name() -> str:
    return (current_app.config.get('WEBAUTHN_RP_NAME') or 'CoachHub Hockey').strip()


def expected_origins() -> list:
    """Origins accepted for this ceremony (scheme://host[:port])."""
    configured = (current_app.config.get('WEBAUTHN_ORIGIN') or '').strip()
    if configured:
        return [o.strip() for o in configured.split(',') if o.strip()]
    return [request.host_url.rstrip('/')]


# --------------------------------------------------------- challenge store
def _put_challenge(key: str, challenge: bytes) -> None:
    session[key] = {
        'c': base64.urlsafe_b64encode(challenge).decode('ascii').rstrip('='),
        'exp': (datetime.utcnow() + timedelta(seconds=CHALLENGE_TTL_SECONDS)).timestamp(),
    }


def _take_challenge(key: str) -> bytes:
    """Pop the stored challenge. Single-use: it is gone even if it was stale."""
    blob = session.pop(key, None)
    if not isinstance(blob, dict) or not blob.get('c'):
        raise WebAuthnError('challenge_missing')
    try:
        if float(blob.get('exp') or 0) < datetime.utcnow().timestamp():
            raise WebAuthnError('challenge_expired')
    except (TypeError, ValueError):
        raise WebAuthnError('challenge_expired')
    return base64url_to_bytes(blob['c'])


def clear_challenges() -> None:
    session.pop(_REG_CHALLENGE_KEY, None)
    session.pop(_AUTH_CHALLENGE_KEY, None)


# ------------------------------------------------------------- user handle
def new_user_handle() -> str:
    """Opaque, random, 32-byte WebAuthn user handle (base64url).

    Deliberately carries no meaning: not the player's name, not the numeric
    player_id, nothing an authenticator or a synced-credential provider could
    surface as a readable identity.
    """
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('ascii').rstrip('=')


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


# ------------------------------------------------------------ registration
def registration_options(*, user_handle: str, display_label: str, exclude_credential_ids=()):
    """Build creation options. `display_label` is shown by the OS credential
    picker only; it is never persisted by CoachHub and never used as identity."""
    exclude = [PublicKeyCredentialDescriptor(id=base64url_to_bytes(cid))
               for cid in exclude_credential_ids if cid]
    opts = generate_registration_options(
        rp_id=rp_id(),
        rp_name=rp_name(),
        user_id=base64url_to_bytes(user_handle),
        user_name=display_label,
        user_display_name=display_label,
        exclude_credentials=exclude or None,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        timeout=CHALLENGE_TTL_SECONDS * 1000,
    )
    _put_challenge(_REG_CHALLENGE_KEY, opts.challenge)
    return options_to_json(opts)


def verify_registration(credential_json: str) -> dict:
    """Verify a create() response against the stored challenge.

    Returns the durable fields to persist. Raises WebAuthnError on any failure —
    challenge, origin, RP ID and attestation are all checked by py_webauthn with
    no relaxations for localhost.
    """
    challenge = _take_challenge(_REG_CHALLENGE_KEY)
    try:
        verified = verify_registration_response(
            credential=credential_json,
            expected_challenge=challenge,
            expected_origin=expected_origins(),
            expected_rp_id=rp_id(),
            require_user_verification=False,
        )
    except Exception as exc:
        raise WebAuthnError('registration_verification_failed') from exc
    return {
        'credential_id': _b64url(verified.credential_id),
        'public_key': _b64url(verified.credential_public_key),
        'sign_count': int(verified.sign_count or 0),
        'device_type': getattr(verified.credential_device_type, 'value', None),
        'backed_up': bool(verified.credential_backed_up),
    }


# ---------------------------------------------------------- authentication
def authentication_options():
    """Discoverable-credential login: no allowCredentials, so the browser offers
    the user's own passkeys and CoachHub never has to be told who is logging in
    before the ceremony (no username, no name enumeration)."""
    opts = generate_authentication_options(
        rp_id=rp_id(),
        user_verification=UserVerificationRequirement.PREFERRED,
        timeout=CHALLENGE_TTL_SECONDS * 1000,
    )
    _put_challenge(_AUTH_CHALLENGE_KEY, opts.challenge)
    return options_to_json(opts)


def verify_authentication(credential_json: str, *, public_key: str, sign_count: int) -> dict:
    """Verify a get() response for an already-resolved stored credential."""
    challenge = _take_challenge(_AUTH_CHALLENGE_KEY)
    try:
        verified = verify_authentication_response(
            credential=credential_json,
            expected_challenge=challenge,
            expected_origin=expected_origins(),
            expected_rp_id=rp_id(),
            credential_public_key=base64url_to_bytes(public_key),
            credential_current_sign_count=int(sign_count or 0),
            require_user_verification=False,
        )
    except Exception as exc:
        raise WebAuthnError('authentication_verification_failed') from exc
    return {'new_sign_count': int(verified.new_sign_count or 0)}


def credential_id_from_response(credential_json: str) -> str:
    """Read the credential id out of a get() response so the row can be looked
    up BEFORE any signature check (the public key lives on that row)."""
    import json
    try:
        payload = json.loads(credential_json) if isinstance(credential_json, str) else credential_json
        raw = payload.get('rawId') or payload.get('id')
    except Exception as exc:
        raise WebAuthnError('malformed_credential') from exc
    if not raw:
        raise WebAuthnError('malformed_credential')
    # Normalise padding/alphabet so the lookup key matches what we stored.
    try:
        return _b64url(base64url_to_bytes(raw))
    except Exception as exc:
        raise WebAuthnError('malformed_credential') from exc


def is_secure_context() -> bool:
    """WebAuthn requires HTTPS, except on localhost. Used only to render an
    explanatory message — never to bypass verification."""
    host = _strip_port(request.host)
    if host in ('localhost', '127.0.0.1', '::1'):
        return True
    return request.is_secure or (os.getenv('APP_ENV', '').strip().lower() != 'production'
                                 and request.headers.get('X-Forwarded-Proto') == 'https')
