"""Sign exact manifest bytes using an owner-provisioned Ed25519 key; never generate one.

Keep private keys outside the repository and provide them via protected CI secrets.
The updater verifies the packaged public key and requires a signed expiry.
"""
import argparse
import base64
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--private-key', type=Path, required=True)
    parser.add_argument('--key-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    payload = args.manifest.read_bytes()
    data = json.loads(payload)
    if data.get('product') != 'SurveySync' or not data.get('expires_utc'):
        raise ValueError('Manifest requires SurveySync product and expires_utc.')
    key = load_pem_private_key(args.private_key.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError('An Ed25519 private key is required.')
    envelope = {'schema': 'surveysync.signed-manifest.v1', 'key_id': args.key_id,
                'payload': base64.b64encode(payload).decode(),
                'signature': base64.b64encode(key.sign(payload)).decode()}
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(envelope, stream, indent=2)


if __name__ == '__main__':
    main()
