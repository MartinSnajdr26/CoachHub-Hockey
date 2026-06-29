import ipaddress
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_REDIRECT_CODES = {301, 302, 303, 307, 308}


class UnsafeUrlError(ValueError):
    """Raised when a URL (or one of its redirect targets) fails SSRF validation."""


def validate_public_http_url(url: str) -> tuple[bool, str]:
    """Validate a URL before server-side fetching."""
    raw = (url or '').strip()
    if not raw:
        return False, 'URL není vyplněná.'
    parsed = urlparse(raw)
    if parsed.scheme not in ('http', 'https'):
        return False, 'URL musí začínat http:// nebo https://'
    if not parsed.hostname:
        return False, 'URL neobsahuje platný host.'
    try:
        infos = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == 'https' else 80),
            type=socket.SOCK_STREAM,
        )
    except Exception:
        return False, 'Host URL se nepodařilo ověřit.'
    addresses = {info[4][0] for info in infos if info and info[4]}
    if not addresses:
        return False, 'Host URL se nepodařilo ověřit.'
    for addr in addresses:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False, 'URL obsahuje neplatnou IP adresu.'
        if not ip.is_global:
            return False, 'URL nesmí mířit na interní nebo lokální adresu.'
    return True, ''


def _safe_url_for_log(url: str) -> str:
    """scheme://host[:port]/path with query, fragment and credentials stripped,
    so rejected URLs can be logged without leaking secrets/tokens."""
    try:
        p = urllib.parse.urlsplit(url or '')
        host = p.hostname or ''
        if p.port:
            host = '%s:%s' % (host, p.port)
        return '%s://%s%s' % (p.scheme or '?', host, p.path or '')
    except Exception:
        return '<unparseable-url>'


class _NoFollowRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Disables urllib's automatic redirect following so each hop can be
    re-validated by safe_urlopen (urllib otherwise follows 3xx blindly)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def safe_urlopen(url, *, timeout, headers=None, max_redirects=3):
    """Open an http(s) URL with SSRF protection on EVERY hop.

    The initial URL and every redirect ``Location`` are checked with
    ``validate_public_http_url`` (blocks non-http(s) schemes and private /
    loopback / link-local / cloud-metadata addresses). urllib's automatic
    redirect following is disabled; redirects are followed manually and capped at
    ``max_redirects``. Returns the final urllib response (usable as a context
    manager); the caller is responsible for size limits when reading.

    Raises ``UnsafeUrlError`` if any hop is rejected or the redirect budget is
    exceeded; other failures surface as the usual ``urllib`` errors. The socket
    ``timeout`` applies to each hop, preserving existing behaviour."""
    opener = urllib.request.build_opener(_NoFollowRedirectHandler)
    current = url
    for _hop in range(max_redirects + 1):
        ok, msg = validate_public_http_url(current)
        if not ok:
            logger.warning('Blocked unsafe fetch URL %s: %s', _safe_url_for_log(current), msg)
            raise UnsafeUrlError(msg)
        req = urllib.request.Request(current, headers=headers or {})
        try:
            return opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in _REDIRECT_CODES:
                location = exc.headers.get('Location') if exc.headers else None
                if not location:
                    raise
                current = urllib.parse.urljoin(current, location)
                continue
            raise
    logger.warning('Too many redirects fetching %s', _safe_url_for_log(url))
    raise UnsafeUrlError('Příliš mnoho přesměrování (limit %d).' % max_redirects)
