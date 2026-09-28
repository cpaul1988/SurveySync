"""Import reviewed source after validating every before/after digest."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess

ALLOWED = set('''Build_SurveySync.ps1 IMPLEMENTATION_INDEX.json RELEASE_ID.txt
docs/FEATURE_MATRIX.md docs/KNOWN_ISSUES.md docs/REMAINING_AUDIT_WORK.md docs/TEST_COVERAGE.md
installer/SurveySync.iss installer/app_launcher.go installer/app_launcher_test.go installer/update_helper.go
scripts/sign_manifest.py scripts/sign_windows_artifacts.ps1 scripts/verify_optional_backends.py
scripts/verify_remaining_workflows.py scripts/verify_update_cycle.py
surveysync/crs_diagnostic_routes.py surveysync/crs_diagnostics.py surveysync/desktop_context.py
surveysync/gis_bridge_routes.py surveysync/gis_bridges.py surveysync/manifest_trust.py
surveysync/pointcloud.py surveysync/pointcloud_routes.py surveysync/release_identity.py
surveysync/report_template_mapper.py surveysync/report_template_routes.py surveysync/router.py
surveysync/static/app.js surveysync/static/desktop_workflows.js surveysync/static/index.html
surveysync/updater.py surveysync/workflow_engine.py surveysync/workflow_routes.py
tests/test_remaining_audit.py tests/test_remaining_preservation.py update_trust.json'''.split())


def digest(value):
    return hashlib.sha256(value).hexdigest()


def main():
    if os.environ.get('GITHUB_REPOSITORY') != 'cpaul1988/SurveySync' or os.environ.get('GITHUB_REF') != 'refs/heads/fix-v9.4.1-remaining-audit':
        raise RuntimeError('Import is scoped to the unpublished remaining-audit branch.')
    root = Path.cwd().resolve()
    folder = root / '.github/remaining-import'
    raw = gzip.decompress(b''.join((folder/f'part{i:02d}.gzpart').read_bytes() for i in range(1,10)))
    if len(raw) != 114279 or digest(raw) != '1696bb190b43ef74910e7431b59b19fc8f498c034fed16426d44af14b943e096':
        raise RuntimeError('Reviewed payload digest mismatch.')
    items = json.loads(raw)
    if len(items) != len(ALLOWED) or {i['path'] for i in items} != ALLOWED:
        raise RuntimeError('Unexpected source paths.')
    writes = []
    for item in items:
        path = root/item['path']
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise RuntimeError('Unsafe source path.')
        if item['before'] is None:
            if path.exists():
                raise RuntimeError('New source already exists: ' + item['path'])
            old = ''
        else:
            old = path.read_text(encoding='utf-8')
            if digest(old.encode()) != item['before']:
                raise RuntimeError('Source changed; review required: ' + item['path'])
        previous_end = 0
        for start,end,replacement in item['changes']:
            if not (previous_end <= start <= end <= len(old)) or not isinstance(replacement,str):
                raise RuntimeError('Invalid or overlapping source changes.')
            previous_end = end
        new = old
        for start,end,replacement in reversed(item['changes']):
            new = new[:start] + replacement + new[end:]
        content = new.encode('utf-8')
        if digest(content) != item['after']:
            raise RuntimeError('Repaired source digest mismatch: ' + item['path'])
        writes.append((path,content))
    for path,content in writes:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(content)
    subprocess.run(['git','add','--',*sorted(ALLOWED)],check=True)
    print(f'Imported {len(writes)} reviewed files. No public release or feed changed.')


if __name__ == '__main__':
    main()
