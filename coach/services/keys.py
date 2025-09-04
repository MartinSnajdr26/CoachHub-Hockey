import os
import base64
import hashlib
from hmac import compare_digest


def _scrypt(password: bytes, salt: bytes, n=2**14, r=8, p=1, dklen=32) -> bytes:
    return hashlib.scrypt(password=password, salt=salt, n=n, r=r, p=p, dklen=dklen)


def hash_team_key(plaintext: str) -> str:
    """Return PHC-like encoded hash using scrypt: scrypt$N$r$p$base64salt$base64hash"""
    salt = os.urandom(16)
    key = _scrypt(plaintext.encode('utf-8'), salt)
    return 'scrypt$16384$8$1$%s$%s' % (base64.b64encode(salt).decode('ascii'), base64.b64encode(key).decode('ascii'))


def verify_team_key(plaintext: str, encoded: str) -> bool:
    try:
        algo, n, r, p, b64salt, b64hash = encoded.split('$')
        if algo != 'scrypt':
            return False
        salt = base64.b64decode(b64salt)
        expected = base64.b64decode(b64hash)
        derived = _scrypt(plaintext.encode('utf-8'), salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return compare_digest(derived, expected)
    except Exception:
        return False


def gen_plain_key(length: int = 24) -> str:
    # URL-safe key (no padding)
    return base64.urlsafe_b64encode(os.urandom(length)).decode('ascii').rstrip('=')

