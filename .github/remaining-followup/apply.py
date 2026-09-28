"""Apply a reviewed source delta after verifying every before/after digest."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess

ALLOWED = set('''scripts/update_manifest.py surveysync/gis_bridges.py surveysync/manifest_trust.py
surveysync/report_template_mapper.py surveysync/static/desktop_workflows.js
tests/test_remaining_followup.py tests/test_v940_crs_report_gis_bridges.py'''.split())

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def main():
    if os.environ.get('GITHUB_REPOSITORY') != 'cpaul1988/SurveySync' or os.environ.get('GITHUB_REF') != 'refs/heads/fix-v9.4.1-remaining-audit':
        raise RuntimeError('Import is permitted only on the unpublished audit branch.')
    root = Path.cwd().resolve()
    folder = root / '.github/remaining-followup'
    raw = gzip.decompress(b''.join((folder/f'part{i:02d}.gzpart').read_bytes() for i in (1,2)))
    if len(raw) != 19938 or digest(raw) != '5124710e19e1e815855ca9f71cae65ee94abccca91029ffd4fd8e690f594d764':
        raise RuntimeError('Reviewed payload checksum mismatch.')
    items = json.loads(raw)
    if len(items) != len(ALLOWED) or {i['path'] for i in items} != ALLOWED:
        raise RuntimeError('Unexpected source paths.')
    writes = []
    for item in items:
        path = root / item['path']
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise RuntimeError('Unsafe source path.')
        if item['before'] is None:
            if path.exists():
                raise RuntimeError('New source path already exists: '+item['path'])
            old = ''
        else:
            old = path.read_text(encoding='utf-8')
            if digest(old.encode()) != item['before']:
                raise RuntimeError('Source changed; review required: '+item['path'])
        previous_end = 0
        for start,end,replacement in item['changes']:
            if not (previous_end <= start <= end <= len(old)) or not isinstance(replacement,str):
                raise RuntimeError('Invalid/overlapping source edits.')
            previous_end = end
        new = old
        for start,end,replacement in reversed(item['changes']):
            new = new[:start] + replacement + new[end:]
        content = new.encode('utf-8')
        if digest(content) != item['after']:
            raise RuntimeError('After checksum mismatch: '+item['path'])
        writes.append((path,content))
    for path,content in writes:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(content)
    subprocess.run(['git','add','--',*sorted(ALLOWED)],check=True)
    print(f'Applied {len(writes)} verified follow-up files; no published metadata changed.')

if __name__ == '__main__':
    main()
