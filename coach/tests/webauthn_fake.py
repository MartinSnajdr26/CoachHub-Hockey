"""A minimal software WebAuthn authenticator for tests.

Produces REAL ES256 credentials and signatures, so `py_webauthn` performs its
genuine verification (challenge, origin, RP ID hash, signature, sign counter).
Nothing in the server's verification path is stubbed or relaxed — the only thing
faked is the hardware that would normally hold the key.

Deliberately supports the abuse cases too (`wrong_origin`, `tamper_signature`,
replayed counters), so the tests can prove verification actually rejects them.
"""
import base64
import hashlib
import json
import os
import struct

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

FLAG_UP = 0x01          # user present
FLAG_UV = 0x04          # user verified
FLAG_BE = 0x08          # backup eligible
FLAG_BS = 0x10          # backed up
FLAG_AT = 0x40          # attested credential data included


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def b64url_decode(val: str) -> bytes:
    pad = '=' * (-len(val) % 4)
    return base64.urlsafe_b64decode(val + pad)


class SoftAuthenticator:
    """One virtual passkey (one key pair, one credential id)."""

    def __init__(self, *, credential_id: bytes = None, sign_count: int = 0):
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = credential_id or os.urandom(32)
        self.sign_count = sign_count
        self.aaguid = b'\x00' * 16

    # -- key encoding -----------------------------------------------------
    def _cose_key(self) -> bytes:
        nums = self.private_key.public_key().public_numbers()
        return cbor2.dumps({
            1: 2,                                     # kty: EC2
            3: -7,                                    # alg: ES256
            -1: 1,                                    # crv: P-256
            -2: nums.x.to_bytes(32, 'big'),
            -3: nums.y.to_bytes(32, 'big'),
        })

    def _auth_data(self, rp_id: str, flags: int, sign_count: int, attested: bool) -> bytes:
        data = hashlib.sha256(rp_id.encode('utf-8')).digest()
        data += struct.pack('!B', flags)
        data += struct.pack('!I', sign_count)
        if attested:
            data += self.aaguid
            data += struct.pack('!H', len(self.credential_id))
            data += self.credential_id
            data += self._cose_key()
        return data

    @staticmethod
    def _client_data(kind: str, challenge_b64url: str, origin: str) -> bytes:
        return json.dumps({
            'type': kind,
            'challenge': challenge_b64url,
            'origin': origin,
            'crossOrigin': False,
        }, separators=(',', ':')).encode('utf-8')

    # -- ceremonies -------------------------------------------------------
    def create(self, options: dict, *, origin: str, rp_id: str = None,
               backed_up: bool = True) -> dict:
        """Answer a registration ceremony ('none' attestation)."""
        rp_id = rp_id or options['rp']['id']
        client_data = self._client_data('webauthn.create', options['challenge'], origin)
        flags = FLAG_UP | FLAG_UV | FLAG_AT | (FLAG_BE | FLAG_BS if backed_up else 0)
        auth_data = self._auth_data(rp_id, flags, self.sign_count, attested=True)
        attestation = cbor2.dumps({'fmt': 'none', 'attStmt': {}, 'authData': auth_data})
        return {
            'id': b64url(self.credential_id),
            'rawId': b64url(self.credential_id),
            'type': 'public-key',
            'clientExtensionResults': {},
            'response': {
                'clientDataJSON': b64url(client_data),
                'attestationObject': b64url(attestation),
                'transports': ['internal', 'hybrid'],
            },
        }

    def get(self, options: dict, *, origin: str, rp_id: str = None,
            user_handle: str = None, sign_count: int = None,
            tamper_signature: bool = False) -> dict:
        """Answer an authentication ceremony."""
        rp_id = rp_id or options['rpId']
        if sign_count is None:
            self.sign_count += 1
            sign_count = self.sign_count
        client_data = self._client_data('webauthn.get', options['challenge'], origin)
        auth_data = self._auth_data(rp_id, FLAG_UP | FLAG_UV, sign_count, attested=False)
        payload = auth_data + hashlib.sha256(client_data).digest()
        signature = self.private_key.sign(payload, ec.ECDSA(hashes.SHA256()))
        if tamper_signature:
            signature = signature[:-1] + bytes([signature[-1] ^ 0xFF])
        return {
            'id': b64url(self.credential_id),
            'rawId': b64url(self.credential_id),
            'type': 'public-key',
            'clientExtensionResults': {},
            'response': {
                'clientDataJSON': b64url(client_data),
                'authenticatorData': b64url(auth_data),
                'signature': b64url(signature),
                'userHandle': user_handle,
            },
        }
