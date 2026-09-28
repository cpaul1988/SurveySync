"""Publish only the exact independently accepted 9.4.2 installer, without rebuilding.

The approval receipt is committed only after reviewing completed Windows runs.
Read-only validation precedes PR merge, tag/release creation and update-feed writes.
"""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from datetime import datetime, timezone

REPO = 'cpaul1988/SurveySync'
ROOT = 'repos/' + REPO
BRANCH = 'fix-v9.4.1-remaining-audit'
TAG = 'v9.4.2'
RECEIPT = '.github/release-942.json'
FILES = {'SurveySync_Setup_9.4.2-beta.2.exe', 'SurveySync_Setup_9.4.2-beta.2.exe.sha256',
         'RELEASE_NOTES_v9_4_2.md', 'QA_REPORT_v9_4_2.md', 'VERSION.txt', 'RELEASE_ID.txt'}
WORKFLOWS = {'acceptance': '.github/workflows/repair-acceptance.yml',
             'quality': '.github/workflows/quality.yml',
             'ui': '.github/workflows/ui-validation.yml',
             'remaining': '.github/workflows/remaining-audit.yml'}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def gh(*args, data=None, optional=False):
    proc = subprocess.run(['gh', *args], input=data, text=True, encoding='utf-8',
                          capture_output=True, check=False)
    if proc.returncode:
        if optional and 'HTTP 404' in proc.stderr:
            return None
        raise RuntimeError(proc.stderr.strip() or 'GitHub command failed')
    return proc.stdout


def api(path, method='GET', body=None, optional=False):
    args = ['api', path, '--method', method]
    if body is not None:
        args += ['--input', '-']
    raw = gh(*args, data=None if body is None else json.dumps(body), optional=optional)
    return None if raw is None else json.loads(raw)


def validate_receipt(r):
    require(r.get('version') == '9.4.2' and r.get('publish_stable') is True,
            'Receipt must explicitly authorize 9.4.2 Stable')
    for key in ('source_sha', 'base_sha'):
        require(re.fullmatch('[0-9a-f]{40}', str(r.get(key, ''))), 'Invalid source/base SHA')
    require(set(r.get('runs', {})) == set(WORKFLOWS), 'Four independent acceptance runs required')
    require(all(type(x) is int and x > 0 for x in r['runs'].values()), 'Invalid run IDs')
    require(type(r.get('artifact_id')) is int and r['artifact_id'] > 0, 'Invalid artifact ID')
    require(re.fullmatch('[0-9a-f]{64}', str(r.get('archive_sha256', ''))), 'Invalid artifact digest')
    require(set(r.get('files', {})) == FILES, 'Unexpected release files')
    for name, info in r['files'].items():
        require(re.fullmatch('[0-9a-f]{64}', str(info.get('sha256', ''))), 'Invalid file hash: ' + name)
        require(type(info.get('size')) is int and info['size'] > 0, 'Invalid file size: ' + name)


def verify_file(path, info):
    require(path.is_file() and path.stat().st_size == info['size'], 'Release file missing/size mismatch: ' + path.name)
    require(hashlib.sha256(path.read_bytes()).hexdigest() == info['sha256'], 'Release file hash mismatch: ' + path.name)


def load_feed():
    entry = api(ROOT + '/contents/update.json?ref=main')
    require(entry.get('encoding') == 'base64', 'Unexpected feed encoding')
    data = json.loads(base64.b64decode(entry['content']).decode('utf-8-sig'))
    require(data.get('product') == 'SurveySync' and isinstance(data.get('channels'), dict), 'Invalid live feed')
    for channel in ('stable', 'beta'):
        value = str(data['channels'].get(channel, {}).get('version', ''))
        require(re.fullmatch(r'\d+\.\d+\.\d+', value), 'Unrecognized existing channel version')
        require(tuple(map(int, value.split('.'))) <= (9, 4, 2), 'Refusing to downgrade a newer channel')
    return entry, data


def find_release(tag):
    for page in range(1, 101):
        values = api(f'{ROOT}/releases?per_page=100&page={page}')
        matches = [x for x in values if x['tag_name'] == tag]
        require(len(matches) <= 1, 'Ambiguous release tag')
        if matches:
            return matches[0]
        if len(values) < 100:
            return None
    raise RuntimeError('Release listing exceeded safe pagination bound')


def channel_entries(data, r, notes, timestamp):
    result = copy.deepcopy(data)
    exe = r['files']['SurveySync_Setup_9.4.2-beta.2.exe']
    for channel in ('beta', 'stable'):
        prior = data['channels'].get(channel, {})
        if prior.get('version') == '9.4.2':
            require(prior.get('sha256') == exe['sha256'] and prior.get('release_tag') == TAG,
                    'Conflicting 9.4.2 already exists on ' + channel)
        entry = {'version': '9.4.2', 'release_id': '9.4.2-beta.2', 'channel': channel, 'publisher': 'Clever Bird Development',
                 'installer_url': f'https://github.com/{REPO}/releases/download/{TAG}/SurveySync_Setup_9.4.2-beta.2.exe',
                 'size_bytes': exe['size'], 'sha256': exe['sha256'],
                 'artifact_identity': 'sha256:' + exe['sha256'], 'release_tag': TAG,
                 'release_notes': notes, 'required': False, 'published_utc': timestamp}
        if channel == 'stable':
            entry.update(promoted_from='beta', promoted_utc=timestamp,
                         tested_channel_published_utc=timestamp)
        result['channels'][channel] = entry
    return result


def main():
    require(os.environ.get('GITHUB_REPOSITORY') == REPO, 'Wrong repository')
    require(os.environ.get('GITHUB_REF') == 'refs/heads/' + BRANCH, 'Wrong publication branch')
    require(os.environ.get('GITHUB_EVENT_NAME') == 'push', 'Explicit receipt push required')
    receipt = json.loads(Path(RECEIPT).read_text(encoding='utf-8'))
    validate_receipt(receipt)
    head = os.environ['GITHUB_SHA']
    compare = api(f'{ROOT}/compare/{receipt["source_sha"]}...{head}')
    require(compare['status'] == 'ahead' and compare['ahead_by'] == 1 and compare['behind_by'] == 0
            and RECEIPT in {f['filename'] for f in compare.get('files', [])}
            and {f['filename'] for f in compare.get('files', [])} <= {RECEIPT,
                '.github/workflows/release.yml', '.github/scripts/publish_verified_942.py',
                '.github/scripts/tests/test_publish_verified_942.py'},
            'Publication head must differ from tested source only by its approval receipt and reviewed publisher infrastructure')
    require(api(f'{ROOT}/git/ref/heads/{BRANCH}')['object']['sha'] == head, 'Candidate branch moved')
    for key, path in WORKFLOWS.items():
        run = api(f'{ROOT}/actions/runs/{receipt["runs"][key]}')
        require(run['status'] == 'completed' and run['conclusion'] == 'success'
                and run['head_sha'] == receipt['source_sha'] and run['head_branch'] == BRANCH
                and run['path'] == path and run['repository']['full_name'] == REPO,
                'Approved Windows check invalid: ' + key)
    artifact = api(f'{ROOT}/actions/artifacts/{receipt["artifact_id"]}')
    require(not artifact['expired'] and artifact['name'] == 'SurveySync_9.4.2_beta2_Verified_Installer'
            and artifact['digest'] == 'sha256:' + receipt['archive_sha256']
            and artifact['workflow_run']['id'] == receipt['runs']['acceptance']
            and artifact['workflow_run']['head_sha'] == receipt['source_sha'], 'Artifact provenance mismatch')
    with tempfile.TemporaryDirectory(prefix='verified-942-') as temp:
        folder = Path(temp)
        gh('run', 'download', str(receipt['runs']['acceptance']), '--repo', REPO,
           '--name', 'SurveySync_9.4.2_beta2_Verified_Installer', '--dir', temp)
        paths = {}
        for name, info in receipt['files'].items():
            matches = list(folder.rglob(name))
            require(len(matches) == 1, 'Expected exactly one ' + name)
            verify_file(matches[0], info)
            paths[name] = matches[0]
        require(paths['SurveySync_Setup_9.4.2-beta.2.exe'].read_bytes()[:2] == b'MZ', 'Invalid executable header')
        require(paths['VERSION.txt'].read_text().strip() == '9.4.2', 'Packaged version mismatch')
        require(paths['RELEASE_ID.txt'].read_text().strip() == '9.4.2-beta.2', 'Packaged release identity mismatch')
        notes = paths['RELEASE_NOTES_v9_4_2.md'].read_text(encoding='utf-8-sig').strip()
        notes = ('Promoted to Stable by CP on 2026-09-28. Exact accepted beta.2 installer bytes; physical release identity remains 9.4.2-beta.2. No rebuild.\n\n'
                 'Field validation remains pending for GTX1650/Paddle/Qwen accuracy, speed and blocked-read cancellation; official Trimble .job conversion; and rod confidence calibration. Production signing is not activated.\n\n' + notes)
        entry, data = load_feed()
        # Validate version conflicts before changing the PR or release.
        channel_entries(data, receipt, notes, '')
        tag_ref = api(f'{ROOT}/git/ref/tags/{TAG}', optional=True)
        if tag_ref is not None:
            require(tag_ref['object']['type'] == 'commit' and tag_ref['object']['sha'] == receipt['source_sha'], 'Existing tag conflicts; never move it')
        pr = api(f'{ROOT}/pulls/13')
        require(pr['head']['sha'] == head and pr['base']['ref'] == 'main', 'PR source changed')
        if not pr['merged']:
            require(api(f'{ROOT}/git/ref/heads/main')['object']['sha'] == receipt['base_sha'],
                    'Main changed after review; reconcile before publication')
            if pr['draft']:
                gh('pr', 'ready', '13', '--repo', REPO)
            merged = api(f'{ROOT}/pulls/13/merge', 'PUT',
                         {'sha': head, 'merge_method': 'merge', 'commit_title': 'Merge verified SurveySync 9.4.2 audit repairs'})
            require(merged.get('merged'), 'GitHub did not merge the accepted source')
        else:
            relation = api(f'{ROOT}/compare/{pr["merge_commit_sha"]}...main')
            require(relation['behind_by'] == 0 and all(f['filename'] == 'update.json' for f in relation.get('files', [])),
                    'Main changed beyond the publication feed; stop')
        ref = api(f'{ROOT}/git/ref/tags/{TAG}', optional=True)
        if ref is None:
            ref = api(f'{ROOT}/git/refs', 'POST', {'ref': 'refs/tags/' + TAG, 'sha': receipt['source_sha']})
        require(ref['object']['type'] == 'commit' and ref['object']['sha'] == receipt['source_sha'], 'Existing tag conflicts; never move it')
        body = (f'## Verified 9.4.2 release\n\nExact installer from Windows Repair Acceptance run {receipt["runs"]["acceptance"]}; no rebuild. '
                'Both the installed native workflows and the update replacement fixtures passed. '
                'The unmodified 9.4.0 migration needs one normal window close because its old shutdown bug cannot be repaired before installing this update.\n\n'
                + notes)
        release = find_release(TAG)
        if release is None:
            release = api(ROOT + '/releases', 'POST', {'tag_name': TAG, 'target_commitish': receipt['source_sha'],
                          'name': 'SurveySync 9.4.2 [stable]', 'body': body, 'draft': True,
                          'prerelease': False, 'make_latest': 'false'})
        require((release.get('body') or '').replace('\r\n', '\n').strip() == body.strip(), 'Existing release notes differ')
        assets = {a['name']: a for a in release.get('assets', [])}
        require(set(assets) <= FILES, 'Unexpected existing release assets')
        missing = [str(p) for n, p in paths.items() if n not in assets]
        if missing:
            require(release['draft'], 'Published release incomplete; refuse asset modification')
            gh('release', 'upload', TAG, *missing, '--repo', REPO)
        with tempfile.TemporaryDirectory(prefix='942-recheck-') as verify:
            for name, info in receipt['files'].items():
                gh('release', 'download', TAG, '--repo', REPO, '--pattern', name, '--dir', verify)
                verify_file(Path(verify)/name, info)
        release = api(f'{ROOT}/releases/{release["id"]}', 'PATCH',
                      {'draft': False, 'prerelease': False, 'make_latest': 'true', 'name': 'SurveySync 9.4.2 [stable]'})
        require(not release['draft'] and not release['prerelease'], 'Release status not confirmed')
        entry, data = load_feed()
        updated = channel_entries(data, receipt, notes, release['published_at'])
        unchanged = {k: copy.deepcopy(v) for k, v in data['channels'].items() if k not in ('beta', 'stable')}
        if updated['channels'] != data['channels']:
            updated['generated_utc'] = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
            updated['publisher_tool'] = 'GitHub Actions'
            content = base64.b64encode((json.dumps(updated, indent=2, ensure_ascii=False) + '\n').encode()).decode()
            api(ROOT + '/contents/update.json', 'PUT', {'branch': 'main', 'sha': entry['sha'], 'content': content,
                 'message': 'Publish verified SurveySync 9.4.2 to Beta and Stable; preserve Developer'})
        _, live = load_feed()
        require(live['channels'] == updated['channels'], 'Live channels differ from verified publication')
        require({k:v for k,v in live['channels'].items() if k not in ('beta','stable')} == unchanged, 'Unrelated channel changed')
        latest = api(ROOT + '/releases/latest')
        require(latest['id'] == release['id'] and latest['tag_name'] == TAG and not latest['prerelease'], 'GitHub Latest not updated')
        summary = (f'## Published SurveySync 9.4.2 Stable\n\nRelease: {release["html_url"]}\n\n'
                   f'Installer SHA-256: `{receipt["files"]["SurveySync_Setup_9.4.2-beta.2.exe"]["sha256"]}`\n\n'
                   'Exact accepted installer reused; source PR merged; Beta/Stable and GitHub Latest verified; Developer preserved.\n')
        print(summary)
        Path(os.environ['GITHUB_STEP_SUMMARY']).write_text(summary, encoding='utf-8')

if __name__ == '__main__':
    main()
