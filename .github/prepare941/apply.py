"""Hash-verified import of the reviewed 9.4.1 repair/version changes."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess

ALLOWED = set('''BUILD_MANIFEST.json CHANGELOG.md IMPLEMENTATION_INDEX.json
QA_REPORT_v9_4_1.md RELEASE_NOTES_v9_4_1.md VERSION.txt desktop.py
fieldbook_sync/static/index.html installer/SurveySync.iss installer/app_launcher.go
installer/app_launcher_test.go installer/provision_runtime.ps1 installer/update_helper.go
installer/update_helper_test.go scripts/theme_branding_smoke.py scripts/ui_browser_smoke.py
scripts/verify_repaired_ui.py scripts/verify_update_cycle.py surveysync/__init__.py
surveysync/router.py surveysync/static/app.js surveysync/static/index.html surveysync/updater.py
tests/test_beta3_ui.py tests/test_theme_branding.py tests/test_v940_beta2_brand_release_notes.py
tests/test_v941_updater.py'''.split())

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def main():
    if os.environ.get('GITHUB_REPOSITORY') != 'cpaul1988/SurveySync' or os.environ.get('GITHUB_REF') != 'refs/heads/fix-v9.4.0-verified-audit':
        raise RuntimeError('Import only permitted on the isolated repair branch.')
    root = Path.cwd().resolve()
    source = root / '.github/prepare941'
    raw = gzip.decompress(b''.join((source/f'part{i:02d}.gzpart').read_bytes() for i in range(1,10)))
    if len(raw) != 51505 or digest(raw) != 'eb0d74a2631ca2a259a51e9f2f77b3d317dbe7c40d2e6fba5d80464be4ff8087':
        raise RuntimeError('Reviewed source payload checksum mismatch.')
    items = json.loads(raw)
    if len(items) != len(ALLOWED) or {i['path'] for i in items} != ALLOWED:
        raise RuntimeError('Unexpected source paths.')
    writes = []
    for item in items:
        path = root/item['path']
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise RuntimeError('Unsafe source path.')
        if item['before'] is None:
            if path.exists(): raise RuntimeError(f'New path exists: {path}')
            old = ''
        else:
            old = path.read_text(encoding='utf-8')
            if digest(old.encode()) != item['before']:
                raise RuntimeError(f'Source changed; review required: {item["path"]}')
        end_previous = 0
        for start,end,replacement in item['changes']:
            if not (end_previous <= start <= end <= len(old)) or not isinstance(replacement,str):
                raise RuntimeError('Invalid source edit.')
            end_previous = end
        new = old
        for start,end,replacement in reversed(item['changes']):
            new = new[:start]+replacement+new[end:]
        encoded = new.encode('utf-8')
        if digest(encoded) != item['after']:
            raise RuntimeError(f'After hash mismatch: {item["path"]}')
        writes.append((path,encoded))
    for path,encoded in writes:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(encoded)
    subprocess.run(['git','add','--',*sorted(ALLOWED)],check=True)
    print(f'Imported {len(writes)} verified files; version 9.4.1; update feed and releases unchanged.')

if __name__ == '__main__': main()
