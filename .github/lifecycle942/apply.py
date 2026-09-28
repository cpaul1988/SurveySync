"""Import the reviewed lifecycle correction on the unpublished candidate only."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess

ALLOWED = set('''fieldbook_sync/app.py surveysync/router.py surveysync/ai_runtime.py
scripts/verify_lifecycle_stress.py surveysync/http_shutdown.py
surveysync/status_probe_process.py surveysync/ai_status_probe.py
tests/test_exit_response_ordering.py tests/test_bounded_ai_status.py
docs/CANDIDATE_942_LIFECYCLE_FOLLOWUP.md RELEASE_NOTES_v9_4_2.md'''.split())


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    if os.environ.get('GITHUB_REPOSITORY') != 'cpaul1988/SurveySync' or os.environ.get('GITHUB_REF') != 'refs/heads/fix-v9.4.1-remaining-audit':
        raise RuntimeError('Import is restricted to the unpublished audit candidate.')
    root = Path.cwd().resolve()
    folder = root/'.github/lifecycle942'
    raw = gzip.decompress(b''.join((folder/f'part{i}.gzpart').read_bytes() for i in range(1,5)))
    if len(raw) != 27093 or digest(raw) != 'ec23045f26a29120bf40ac55a9bb4c13f30b2f331b071cf07947b9798d3e0310':
        raise RuntimeError('Reviewed lifecycle payload checksum mismatch.')
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
                raise RuntimeError('New source already exists: '+item['path'])
            old = ''
        else:
            old = path.read_text(encoding='utf-8')
            if digest(old.encode()) != item['before']:
                raise RuntimeError('Source changed; review required: '+item['path'])
        previous_end = 0
        for start,end,replacement in item['changes']:
            if not (previous_end <= start <= end <= len(old)) or not isinstance(replacement,str):
                raise RuntimeError('Invalid or overlapping edit.')
            previous_end = end
        new = old
        for start,end,replacement in reversed(item['changes']):
            new = new[:start]+replacement+new[end:]
        content = new.encode('utf-8')
        if digest(content) != item['after']:
            raise RuntimeError('After checksum mismatch: '+item['path'])
        writes.append((path,content))
    for path,content in writes:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(content)
    subprocess.run(['git','add','--',*sorted(ALLOWED)],check=True)
    print(f'Imported {len(writes)} reviewed files. No workflow permissions, release or feed changed.')


if __name__ == '__main__':
    main()
