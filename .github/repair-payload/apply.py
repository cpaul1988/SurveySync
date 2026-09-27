"""Import the hash-pinned, reviewed repair package on its isolated branch only."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess

BRANCH = 'fix-v9.4.0-verified-audit'
REPO = 'cpaul1988/SurveySync'
DIGEST = 'bbe73d6b6f96ac61a7692a9d55f38bcc327e58220af87d41b27dad28823d61f0'
ALLOWED = set('''UNRELEASED_REPAIR_NOTES.md desktop.py docs/VERIFIED_AUDIT_REPAIRS.md
fieldbook_sync/job_engine.py installer/SurveySync.iss scripts/verify_repaired_native.py
scripts/verify_repaired_ui.py surveysync/api_models.py surveysync/audit.py
surveysync/cogo_extended.py surveysync/control.py surveysync/control_exports.py
surveysync/control_selection.py surveysync/field_to_finish.py surveysync/leveling.py
surveysync/manual_control.py surveysync/project.py surveysync/reporting.py
surveysync/router.py surveysync/static/app.js surveysync/static/index.html
surveysync/survey_routes.py surveysync/survey_validation.py surveysync/traverse.py
surveysync/utility.py tests/test_audit_reproductions.py
tests/test_shutdown_bridge_contract.py tests/test_verified_repairs.py'''.split())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    if os.environ.get('GITHUB_REPOSITORY') != REPO or os.environ.get('GITHUB_REF') != 'refs/heads/' + BRANCH:
        raise RuntimeError('This import is permitted only on the unpublished repair branch.')
    root = Path.cwd().resolve()
    source = root / '.github/repair-payload'
    raw = gzip.decompress(b''.join((source / f'part{i:02d}.gzpart').read_bytes() for i in range(1, 9)))
    if len(raw) != 68969 or digest(raw) != DIGEST:
        raise RuntimeError('Reviewed payload checksum mismatch.')
    items = json.loads(raw)
    if len(items) != len(ALLOWED) or {i['path'] for i in items} != ALLOWED:
        raise RuntimeError('Unexpected repair paths.')
    writes = []
    for item in items:
        path = root / item['path']
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise RuntimeError('Unsafe repair path.')
        if item['before'] is None:
            if path.exists():
                raise RuntimeError(f'New repair path already exists: {item["path"]}')
            old = ''
        else:
            old = path.read_text(encoding='utf-8')
            if digest(old.encode()) != item['before']:
                raise RuntimeError(f'Source changed; review required: {item["path"]}')
        previous_end = 0
        for start, end, replacement in item['changes']:
            if not (previous_end <= start <= end <= len(old)) or not isinstance(replacement, str):
                raise RuntimeError('Invalid or overlapping source edit.')
            previous_end = end
        new = old
        for start, end, replacement in reversed(item['changes']):
            new = new[:start] + replacement + new[end:]
        encoded = new.encode('utf-8')
        if digest(encoded) != item['after']:
            raise RuntimeError(f'Repaired source checksum mismatch: {item["path"]}')
        writes.append((path, encoded))
    # Validate every file first, then write; do not touch version/update/release files.
    for path, encoded in writes:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
    subprocess.run(['git', 'add', '--', *sorted(ALLOWED)], check=True)
    print(f'Imported {len(writes)} reviewed source files; payload SHA-256 {DIGEST}')


if __name__ == '__main__':
    main()
