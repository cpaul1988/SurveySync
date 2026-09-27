"""Publish CP's approved Beta.4 bytes; never rebuild or promote Stable."""
import base64
import copy
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = 'cpaul1988/SurveySync'
BRANCH = 'v9.4.0-beta4-theme-branding'
SHA = '1382bff0dc5b6bc452d7d64be5f6ac17cd2177a0'
TAG = 'v9.4.0-beta.4'
RUN = 36294542913
QUALITY_RUN = 36294542902
ARTIFACT = 10923766429
ARCHIVE_HASH = '923d21cae10a186e2681770ac3e3fee1bc64abbb336bd9082c4b43df809f5b29'
EXPECTED = {
    'SurveySync_Setup_9.4.0.exe': '1660d9bdb329e61242c48b0dfe6d4a254d2d05220829a83cf54b901a10a5ae17',
    'SurveySync_Setup_9.4.0.exe.sha256': '921b33561f2ecd46d2f45b40c63566dc32cedd18fc3d0d765973c10c320cc01b',
    'RELEASE_NOTES_v9_4_0.md': 'c5c343c21ff867c27f9a56a4bbdbf79fbc4ed2d5c7fd1427f4b2bb56925c270d',
}
ROOT = f'repos/{REPO}'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def gh(*args, data=None, optional=False):
    result = subprocess.run(['gh', *args], input=data, text=True, capture_output=True, check=False)
    if result.returncode:
        if optional and 'HTTP 404' in result.stderr:
            return None
        raise RuntimeError(result.stderr.strip() or 'GitHub command failed.')
    return result.stdout


def api(path, method='GET', body=None, optional=False):
    args = ['api', path, '--method', method]
    if body is not None:
        args += ['--input', '-']
    raw = gh(*args, data=None if body is None else json.dumps(body), optional=optional)
    return None if raw is None else json.loads(raw)


def verify(path, digest):
    require(path.is_file(), f'Missing release file: {path.name}')
    require(hashlib.sha256(path.read_bytes()).hexdigest() == digest,
            f'Integrity mismatch: {path.name}. Nothing will be overwritten.')


def load_feed():
    entry = api(f'{ROOT}/contents/update.json?ref=main')
    require(entry.get('encoding') == 'base64', 'Unexpected feed encoding.')
    data = json.loads(base64.b64decode(entry['content']).decode('utf-8-sig'))
    require(data.get('product') == 'SurveySync' and isinstance(data.get('channels'), dict),
            'Invalid live feed; refusing to replace it.')
    current = data['channels'].get('beta', {})
    if current:
        version = str(current.get('version', ''))
        require(re.fullmatch(r'\d+\.\d+\.\d+', version), 'Unrecognized live beta version.')
        current_tuple = tuple(map(int, version.split('.')))
        require(current_tuple <= (9, 4, 0), 'A newer beta is live; refusing a downgrade.')
        if current_tuple == (9, 4, 0):
            current_tag = str(current.get('release_tag', ''))
            require(re.fullmatch(r'v9\.4\.0-beta(?:\.\d+)?', current_tag),
                    'Unrecognized live 9.4.0 beta tag.')
            number = 1 if current_tag == 'v9.4.0-beta' else int(current_tag.rsplit('.', 1)[1])
            require(number <= 4, 'A later 9.4.0 beta is live; refusing a downgrade.')
    return entry, data


def main():
    require(os.environ.get('GITHUB_REPOSITORY') == REPO, 'Wrong repository.')
    require(os.environ.get('GITHUB_REF') == f'refs/heads/{BRANCH}', 'Select the Beta.4 candidate branch, not main.')
    require(os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch', 'Manual publication only.')
    require(os.environ.get('RELEASE_VERSION') == '9.4.0' and os.environ.get('BETA_SUFFIX') == 'beta.4',
            'This approved-artifact handoff is only for 9.4.0 beta.4.')
    for run_id, workflow in ((RUN, '.github/workflows/ui-validation.yml'),
                             (QUALITY_RUN, '.github/workflows/quality.yml')):
        run = api(f'{ROOT}/actions/runs/{run_id}')
        require(run['status'] == 'completed' and run['conclusion'] == 'success'
                and run['head_sha'] == SHA and run['head_branch'] == BRANCH
                and run['path'] == workflow and run['repository']['full_name'] == REPO,
                f'Approved run {run_id} is not a successful check of the approved source.')
    artifact = api(f'{ROOT}/actions/artifacts/{ARTIFACT}')
    require(not artifact['expired'] and artifact['name'] == 'SurveySync_Beta4_Installer'
            and artifact['workflow_run']['id'] == RUN
            and artifact['workflow_run']['head_sha'] == SHA
            and artifact.get('digest') == 'sha256:' + ARCHIVE_HASH,
            'Approved artifact provenance or digest mismatch.')
    directory = Path('approved-beta4')
    files = {}
    for name, digest in EXPECTED.items():
        matches = list(directory.rglob(name))
        require(len(matches) == 1, f'Expected one approved copy of {name}.')
        verify(matches[0], digest)
        files[name] = matches[0]
    executable = files['SurveySync_Setup_9.4.0.exe']
    require(executable.stat().st_size == 8823709 and executable.read_bytes()[:2] == b'MZ',
            'Approved installer size or executable header mismatch.')
    notes = files['RELEASE_NOTES_v9_4_0.md'].read_text(encoding='utf-8-sig').strip()
    load_feed()  # Validate the live feed before creating a tag or release.
    ref = api(f'{ROOT}/git/ref/tags/{TAG}', optional=True)
    if ref is None:
        ref = api(f'{ROOT}/git/refs', 'POST', {'ref': f'refs/tags/{TAG}', 'sha': SHA})
    require(ref['object']['type'] == 'commit' and ref['object']['sha'] == SHA,
            'Release tag is not the approved source. No tag will be moved.')
    release = api(f'{ROOT}/releases/tags/{TAG}', optional=True)
    if release is None:
        gh('release', 'create', TAG, '--repo', REPO, '--verify-tag', '--draft', '--prerelease',
           '--latest=false', '--title', 'SurveySync 9.4.0 [beta.4]', '--notes-file', str(files['RELEASE_NOTES_v9_4_0.md']))
        release = api(f'{ROOT}/releases/tags/{TAG}')
    require(release['prerelease'] and (release.get('body') or '').strip() == notes,
            'Existing release type or notes differ; refusing to overwrite them.')
    existing = {asset['name'] for asset in release.get('assets', [])}
    missing = [str(path) for name, path in files.items() if name not in existing]
    if missing:
        require(release['draft'], 'Published release is incomplete; refusing to modify it.')
        gh('release', 'upload', TAG, *missing, '--repo', REPO)
    with tempfile.TemporaryDirectory(prefix='beta4-release-verify-') as tmp:
        for name, digest in EXPECTED.items():
            gh('release', 'download', TAG, '--repo', REPO, '--pattern', name, '--dir', tmp)
            verify(Path(tmp) / name, digest)
    if release['draft']:
        gh('release', 'edit', TAG, '--repo', REPO, '--draft=false', '--prerelease', '--latest=false')
    release = api(f'{ROOT}/releases/tags/{TAG}')
    require(not release['draft'] and release['prerelease'], 'Prerelease publication was not confirmed.')
    entry, data = load_feed()  # Read fresh and update only beta with optimistic concurrency.
    other_channels = {key: copy.deepcopy(value) for key, value in data['channels'].items() if key != 'beta'}
    timestamp = release['published_at']
    beta = {
        'version': '9.4.0', 'channel': 'beta', 'publisher': 'Clever Bird Development',
        'installer_url': f'https://github.com/{REPO}/releases/download/{TAG}/{executable.name}',
        'size_bytes': 8823709, 'sha256': EXPECTED[executable.name],
        'artifact_identity': 'sha256:' + EXPECTED[executable.name], 'release_tag': TAG,
        'release_notes': notes, 'required': False, 'published_utc': timestamp,
    }
    if data['channels'].get('beta') != beta:
        data['channels']['beta'] = beta
        data['generated_utc'] = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
        data['publisher_tool'] = 'GitHub Actions'
        content = base64.b64encode((json.dumps(data, indent=2, ensure_ascii=False) + '\n').encode()).decode()
        api(f'{ROOT}/contents/update.json', 'PUT', {
            'message': 'Publish approved SurveySync 9.4.0 beta.4 feed (Stable unchanged)',
            'branch': 'main', 'sha': entry['sha'], 'content': content,
        })
    _, live = load_feed()
    require(live['channels'].get('beta') == beta, 'Live beta feed verification failed.')
    require({key: value for key, value in live['channels'].items() if key != 'beta'} == other_channels,
            'Another channel changed concurrently. Review the live feed before proceeding.')
    summary = ('## Published SurveySync 9.4.0 Beta.4\n\n'
               f'- Release: https://github.com/{REPO}/releases/tag/{TAG}\n'
               f'- Reused approved UI run {RUN}; no rebuild.\n'
               f'- Installer SHA-256: `{EXPECTED[executable.name]}`\n'
               '- Live beta feed verified; Stable and Developer preserved.\n')
    print(summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as stream:
            stream.write(summary)


if __name__ == '__main__':
    main()
