"""Apply the exact locally tested candidate; reject any changed preimage."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zlib

ROOT = Path.cwd().resolve()
BRANCH = 'fix/fbr0018-integration'
if os.environ.get('GITHUB_REF') != 'refs/heads/' + BRANCH:
    raise SystemExit('Wrong branch; refusing candidate write')
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
remote = subprocess.check_output(['git', 'ls-remote', 'origin', 'refs/heads/' + BRANCH], text=True).split()[0]
if remote != head:
    raise SystemExit('Branch moved; refusing to overwrite concurrent work')
encoded = ''.join((ROOT / '.candidate/fbr0018' / f'part{i}.b64').read_text() for i in range(6))
payload = zlib.decompress(base64.b64decode(encoded, validate=True))
if hashlib.sha256(payload).hexdigest() != '8c152d6b8acaa7f7432f3a67d638e21e86a35e28fbb909f3e1a4ba292ef5f6a7':
    raise SystemExit('Candidate payload checksum mismatch')
entries = json.loads(payload)
if len(entries) != 43:
    raise SystemExit('Unexpected file count')
prepared = []
seen = set()
for item in entries:
    rel = Path(item['path'])
    if rel.is_absolute() or '..' in rel.parts or str(rel).startswith('.') or str(rel) in seen:
        raise SystemExit('Unsafe or repeated candidate path')
    seen.add(str(rel))
    path = ROOT / rel
    old = path.read_bytes() if path.exists() else b''
    if hashlib.sha256(old).hexdigest() != item['old_sha256']:
        raise SystemExit(f'Preimage mismatch: {rel}')
    text = old.decode('utf-8')
    cursor = len(text)
    for start, end, replacement in reversed(item['edits']):
        if not 0 <= start <= end <= cursor:
            raise SystemExit(f'Overlapping or invalid edit: {rel}')
        text = text[:start] + replacement + text[end:]
        cursor = start
    new = text.encode('utf-8')
    if hashlib.sha256(new).hexdigest() != item['new_sha256']:
        raise SystemExit(f'Postimage mismatch: {rel}')
    prepared.append((path, new))
# All 43 preimages and postimages are checked before writing the first file.
for path, new in prepared:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(new)
subprocess.run(['git', 'add', '--', *sorted(seen)], check=True)
subprocess.run(['git', 'rm', '-r', '--', '.candidate/fbr0018'], check=True)
subprocess.run(['git', 'config', 'user.name', 'github-actions[bot]'], check=True)
subprocess.run(['git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com'], check=True)
subprocess.run(['git', 'commit', '-m', 'fix: integrate FieldBookSync with authoritative project and persistent shell (FBR-0018)'], check=True)
subprocess.run(['git', 'push', 'origin', 'HEAD:refs/heads/' + BRANCH], check=True)
print('Applied exact 9.5.3-beta.1 candidate with verified preimages and postimages.')
