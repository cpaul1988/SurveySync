"""Build a real disposable predecessor installer with only identity stamps changed.

Never tags, publishes or modifies the target source/installer. This fixture exists
solely to exercise replacing two builds with the same numeric application version.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def build_fixture(root: Path, temp: Path) -> tuple[Path, str, list[str]]:
    assert sys.platform == 'win32' and os.environ.get('GITHUB_ACTIONS') == 'true'
    fixture = temp/'numbered-beta-predecessor-source'
    assert fixture.resolve().is_relative_to(Path(os.environ['RUNNER_TEMP']).resolve())
    core=(root/'VERSION.txt').read_text(encoding='utf-8-sig').strip()
    target=(root/'RELEASE_ID.txt').read_text(encoding='utf-8-sig').strip()
    predecessor=core+'-beta.0'
    assert target == core+'-beta.1', 'Review fixture identities for another candidate'
    shutil.copytree(root, fixture, ignore=shutil.ignore_patterns('.git', '.github', '.venv',
        'runtime', '__pycache__', '*.pyc', 'output', '*-evidence', 'released-baseline',
        'baseline-artifact', '.pytest_cache', '.ruff_cache', '.mypy_cache', '.coverage', 'coverage.xml'))
    changed=[]
    for relative in ('RELEASE_ID.txt', 'BUILD_MANIFEST.json', 'installer/SurveySync.iss',
                     'surveysync/static/index.html', 'fieldbook_sync/static/index.html',
                     'surveysync/static/app.js', 'surveysync/router.py'):
        path=fixture/relative
        old=path.read_text(encoding='utf-8')
        assert target in old, relative
        path.write_bytes(old.replace(target, predecessor).replace('\n', '\r\n').encode('utf-8'))
        changed.append(relative)
    for relative in ('VERSION.txt','surveysync/__init__.py','desktop.py','SurveySync.exe',
                     'SurveySyncUpdater.exe','surveysync/updater.py','installer/app_launcher.go',
                     'installer/update_helper.go'):
        assert (fixture/relative).read_bytes() == (root/relative).read_bytes(), relative
    candidates=[Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'Inno Setup 6/ISCC.exe',
                Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Inno Setup 6/ISCC.exe',
                Path(os.environ['LOCALAPPDATA'])/'Programs/Inno Setup 6/ISCC.exe']
    compiler=next((p for p in candidates if p.is_file()), None)
    assert compiler is not None, 'Inno Setup required for real beta predecessor'
    subprocess.run([str(compiler), '/DMyReleaseID='+predecessor,
        str(fixture/'installer/SurveySync.iss')], cwd=fixture/'installer', check=True, timeout=240)
    output=fixture/'installer/output'/f'SurveySync_Setup_{predecessor}.exe'
    assert output.is_file()
    return output, predecessor, changed
