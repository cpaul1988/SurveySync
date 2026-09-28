"""Import reviewed candidate source only after every before/after hash matches."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess

ALLOWED = set('''VERSION.txt RELEASE_ID.txt surveysync/__init__.py desktop.py
installer/app_launcher.go installer/provision_runtime.ps1 installer/SurveySync.iss
Build_SurveySync.ps1 surveysync/static/index.html fieldbook_sync/static/index.html
surveysync/static/app.js surveysync/router.py scripts/ui_browser_smoke.py
scripts/theme_branding_smoke.py scripts/verify_repaired_ui.py scripts/verify_remaining_workflows.py
tests/test_beta3_ui.py tests/test_v940_beta2_brand_release_notes.py tests/test_theme_branding.py
tests/test_remaining_audit.py BUILD_MANIFEST.json IMPLEMENTATION_INDEX.json CHANGELOG.md
.github/workflows/ui-validation.yml .github/workflows/repair-acceptance.yml
scripts/release_gate.py tests/test_v931_release_candidate.py tests/test_v941_updater.py
tests/test_v9_api.py scripts/verify_update_cycle.py scripts/validate_release_identity.py
scripts/build_beta_fixture.py tests/test_release_stamp_contract.py RELEASE_NOTES_v9_4_2.md
QA_REPORT_v9_4_2.md'''.split())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    if os.environ.get('GITHUB_REPOSITORY') != 'cpaul1988/SurveySync' or os.environ.get('GITHUB_REF') != 'refs/heads/fix-v9.4.1-remaining-audit':
        raise RuntimeError('Candidate import is permitted only on the isolated audit branch.')
    root = Path.cwd().resolve()
    payload = root/'.github/prepare942'
    raw = gzip.decompress(b''.join((payload/f'part{i:02d}.gzpart').read_bytes() for i in (1,2,3)))
    if len(raw) != 41989 or digest(raw) != 'f322fa51eaf93ee73bf9f9e4d6619bfb8f1eb54961e60402e67f8dfab9566c21':
        raise RuntimeError('Reviewed candidate payload checksum mismatch.')
    items = json.loads(raw)
    if len(items) != len(ALLOWED) or {item['path'] for item in items} != ALLOWED:
        raise RuntimeError('Unexpected candidate source paths.')
    writes = []
    for item in items:
        path = root/item['path']
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise RuntimeError('Unsafe source path.')
        if item['before'] is None:
            if path.exists():
                raise RuntimeError('New candidate path already exists: '+item['path'])
            old = ''
        else:
            old = path.read_text(encoding='utf-8')
            if digest(old.encode()) != item['before']:
                raise RuntimeError('Source changed; review required: '+item['path'])
        end_previous = 0
        for start,end,replacement in item['changes']:
            if not (end_previous <= start <= end <= len(old)) or not isinstance(replacement,str):
                raise RuntimeError('Invalid/overlapping source change.')
            end_previous = end
        new = old
        for start,end,replacement in reversed(item['changes']):
            new = new[:start]+replacement+new[end:]
        encoded = new.encode('utf-8')
        if digest(encoded) != item['after']:
            raise RuntimeError('Candidate source checksum mismatch: '+item['path'])
        writes.append((path,encoded))
    for path,encoded in writes:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(encoded)
    subprocess.run(['git','add','--',*sorted(ALLOWED)],check=True)
    print(f'Imported {len(writes)} verified source files. No published release/feed changed.')


if __name__ == '__main__':
    main()
