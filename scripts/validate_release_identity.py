"""Reject mismatched numeric versions, prerelease stamps and packaging surfaces."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from surveysync.release_identity import installed_release_id, release_order


def validate(root: Path = ROOT) -> dict:
    version = (root/'VERSION.txt').read_text(encoding='utf-8-sig').strip()
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('VERSION.txt must be an exact three-part numeric version.')
    identity = installed_release_id(version, root)
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-(?:alpha|beta|rc)\.(?:0|[1-9][0-9]*))?', identity):
        raise ValueError('Packaged build identity must be a release or an explicitly numbered prerelease.')
    core = ast.parse((root/'surveysync/__init__.py').read_text(encoding='utf-8'))
    versions = [node.value.value for node in core.body if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == '__version__' for t in node.targets)
        and isinstance(node.value, ast.Constant)]
    if versions != [version]:
        raise ValueError('Python application version differs from VERSION.txt.')
    launcher = (root/'installer/app_launcher.go').read_text(encoding='utf-8')
    if f'var appVersion = "{version}"' not in launcher:
        raise ValueError('Native launcher version differs from VERSION.txt.')
    iss = (root/'installer/SurveySync.iss').read_text(encoding='utf-8')
    required = [f'#define MyAppVersion "{version}"', f'#define MyReleaseID "{identity}"',
        'OutputBaseFilename=SurveySync_Setup_{#MyReleaseID}', 'AppVerName={#MyAppName} {#MyReleaseID}',
        'VersionInfoTextVersion={#MyReleaseID}']
    if any(value not in iss for value in required):
        raise ValueError('Installer numeric/build identity or output filename is inconsistent.')
    for relative in ('surveysync/static/index.html', 'fieldbook_sync/static/index.html'):
        html = (root/relative).read_text(encoding='utf-8')
        if f'SurveySync v{identity}' not in html or f'theme-branding.css?v={identity}' not in html:
            raise ValueError('Shell branding or cache identity differs: '+relative)
    metadata = json.loads((root/'BUILD_MANIFEST.json').read_text(encoding='utf-8'))
    if metadata.get('version') != version or metadata.get('release_id') != identity:
        raise ValueError('Build manifest does not identify the packaged release.')
    return {'version': version, 'release_id': identity, 'prerelease': not bool(release_order(identity)[1])}


if __name__ == '__main__':
    print('Release identity validated:', json.dumps(validate()))
