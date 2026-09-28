"""Optional pinned Ed25519 manifest authentication. Never trust keys from the feed.

Legacy unsigned mode exists for migration. Production strict mode must be enabled
only after an owner-controlled key is provisioned in the packaged trust policy.
"""
import base64
import binascii
import datetime as dt
import json
from pathlib import Path

SCHEMA = 'surveysync.signed-manifest.v1'


def load_policy(root: Path | None = None) -> dict:
    path = (root or Path(__file__).resolve().parents[1]) / 'update_trust.json'
    data = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'require_signature': False, 'keys': {}}
    if not isinstance(data, dict) or type(data.get('require_signature')) is not bool or not isinstance(data.get('keys'), dict):
        raise ValueError('Invalid packaged update trust policy.')
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in data['keys'].items()):
        raise ValueError('Invalid packaged signing key entry.')
    if data['require_signature'] and not data['keys']:
        raise ValueError('Signed updates required but no trusted public key is provisioned.')
    return data


def decode_manifest(raw: bytes, policy: dict | None = None, now: dt.datetime | None = None) -> dict:
    if len(raw) > 1024 * 1024:
        raise ValueError('Update manifest is too large.')
    trust = load_policy() if policy is None else policy
    data = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError('Update manifest must be an object.')
    if data.get('schema') != SCHEMA:
        if trust['require_signature']:
            raise ValueError('A signed update manifest is required; unsigned fallback is disabled.')
        return data
    key_id = data.get('key_id')
    if not isinstance(key_id, str) or key_id not in trust['keys']:
        raise ValueError('Update manifest uses an untrusted signing key.')
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError as exc:
        raise ValueError('Signed updates require the cryptography runtime; no unsigned fallback is allowed.') from exc
    try:
        payload = base64.b64decode(data['payload'], validate=True)
        signature = base64.b64decode(data['signature'], validate=True)
        key = base64.b64decode(trust['keys'][key_id], validate=True)
        Ed25519PublicKey.from_public_bytes(key).verify(signature, payload)
    except (KeyError, TypeError, ValueError, binascii.Error, InvalidSignature) as exc:
        raise ValueError('Update manifest signature verification failed.') from exc
    result = json.loads(payload.decode('utf-8'))
    if not isinstance(result, dict) or result.get('product') != 'SurveySync':
        raise ValueError('Signed update payload has the wrong product.')
    try:
        expiry_text = result.get('expires_utc')
        if not isinstance(expiry_text, str):
            raise ValueError('Missing expiry string')
        expiry = dt.datetime.fromisoformat(expiry_text.replace('Z', '+00:00'))
        if expiry.tzinfo is None or expiry <= (now or dt.datetime.now(dt.timezone.utc)):
            raise ValueError('Expired or unzoned expiry')
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Signed update manifest has expired or lacks a valid expiry.') from exc
    return result
