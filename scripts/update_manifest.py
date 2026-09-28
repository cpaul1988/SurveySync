"""Publish build identity without rebuilding or relabeling the approved executable."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from surveysync.release_identity import installed_release_id, release_order


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(data: dict, *, channel: str, version: str, release_id: str,
                   installer_url: str, release_tag: str, size: int, digest: str,
                   notes: str = '', promoted_from: str = '', timestamp: str) -> dict:
    if not isinstance(data, dict) or data.get('product', 'SurveySync') != 'SurveySync':
        raise ValueError('Wrong or invalid manifest product.')
    channels = data.get('channels', {})
    if not isinstance(channels, dict) or channel not in ('developer', 'beta', 'stable'):
        raise ValueError('Invalid update channels.')
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+){0,3}', version):
        raise ValueError('Application version must be numeric.')
    version_order = release_order(version)
    identity_order = release_order(release_id)
    if identity_order[0] != version_order[0] or release_order(release_tag) != identity_order:
        raise ValueError('Release identity, version and tag must agree.')
    url = urlsplit(installer_url)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment:
        raise ValueError('Installer URL must be an uncredentialed HTTPS URL.')
    if type(size) is not int or size <= 0 or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('Invalid installer size or digest.')
    source = {}
    if promoted_from:
        if channel != 'stable' or promoted_from != 'beta':
            raise ValueError('Only an approved Beta artifact may be promoted to Stable.')
        source = channels.get(promoted_from, {})
        if not isinstance(source, dict) or any(source.get(k) != v for k, v in {
            'version': version, 'sha256': digest, 'installer_url': installer_url,
            'release_tag': release_tag, 'size_bytes': size}.items()):
            raise ValueError('Promotion must retain the exact approved source artifact, tag, size and URL.')
        source_identity = source.get('release_id') or source.get('release_tag') or source.get('version')
        if release_order(source_identity) != identity_order:
            raise ValueError('Promotion must retain the physical installer release identity.')
    elif channel == 'stable' and not identity_order[1]:
        raise ValueError('A prerelease identity requires explicit Beta promotion.')
    prior = channels.get(channel, {})
    if prior:
        if not isinstance(prior, dict):
            raise ValueError('Invalid existing channel; refusing replacement.')
        prior_order = release_order(prior.get('release_id') or prior.get('release_tag') or prior.get('version'))
        if identity_order < prior_order:
            raise ValueError('Refusing to downgrade the channel.')
        if identity_order == prior_order and prior.get('sha256') != digest:
            raise ValueError('Refusing to replace bytes under an existing release identity.')
    result = copy.deepcopy(data)
    result.update(schema_version=1, product='SurveySync', generated_utc=timestamp,
                  publisher_tool='GitHub Actions')
    entry = dict(version=version, release_id=release_id.removeprefix('v'), channel=channel,
                 publisher='Clever Bird Development', installer_url=installer_url, size_bytes=size,
                 sha256=digest, artifact_identity='sha256:' + digest, release_tag=release_tag,
                 release_notes=notes, required=False, published_utc=timestamp)
    if promoted_from:
        entry.update(promoted_from='beta', promoted_utc=timestamp,
                     tested_channel_published_utc=source.get('published_utc', ''))
    result.setdefault('channels', {})[channel] = entry
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', default='update.json')
    parser.add_argument('--channel', choices=['developer', 'beta', 'stable'], required=True)
    for name in ('version', 'installer', 'installer-url', 'release-tag'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--release-id', default='')
    parser.add_argument('--release-notes-file', default='')
    parser.add_argument('--promoted-from', default='')
    ns = parser.parse_args()
    path = Path(ns.manifest)
    # Corrupt/invalid feeds are not silently converted to an empty manifest.
    before = path.read_bytes() if path.exists() else None
    data = json.loads(before.decode('utf-8-sig')) if before is not None else {}
    if ns.promoted_from:
        source = data.get('channels', {}).get(ns.promoted_from, {})
        identity = ns.release_id or source.get('release_id') or source.get('release_tag') or ns.version
    else:
        packaged = installed_release_id(ns.version, ROOT)
        identity = ns.release_id or packaged
        if release_order(identity) != release_order(packaged):
            raise ValueError('Requested identity differs from packaged RELEASE_ID.txt.')
    installer = Path(ns.installer)
    notes = Path(ns.release_notes_file).read_text(encoding='utf-8-sig').strip() if ns.release_notes_file else ''
    updated = build_manifest(data, channel=ns.channel, version=ns.version, release_id=identity,
                             installer_url=ns.installer_url, release_tag=ns.release_tag,
                             size=installer.stat().st_size, digest=sha256(installer), notes=notes,
                             promoted_from=ns.promoted_from,
                             timestamp=datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'))
    current = path.read_bytes() if path.exists() else None
    if current != before:
        raise ValueError('Update feed changed during preparation; reconcile before publishing.')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(json.dumps(updated, indent=2, ensure_ascii=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if Path(name).exists():
            Path(name).unlink()
    print(json.dumps(updated['channels'][ns.channel], indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
