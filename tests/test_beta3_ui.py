"""Regressions from installed Beta.2 screenshots, not just asset existence."""
from pathlib import Path
import importlib.util
import struct
import xml.etree.ElementTree as ET

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from fieldbook_sync.app import app as installed_app
import surveysync.router as routes

ROOT = Path(__file__).resolve().parents[1]


def client():
    assert installed_app is not None
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


@pytest.mark.parametrize('path', sorted((ROOT / 'surveysync/static/workflow-icons').glob('*.svg')))
def test_module_images_are_served_and_decodable(path):
    with client() as http:
        response = http.get('/surveysync-static/workflow-icons/' + path.name)
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('image/svg+xml')
    assert ET.fromstring(response.content).tag.endswith('svg')
    assert response.headers['cache-control'] == 'no-cache'


@pytest.mark.parametrize('name', ('../router.py', '../../feedback.json', 'a\\b', '\x00', '', 'missing.svg'))
def test_nested_static_route_does_not_escape(name):
    with pytest.raises(HTTPException) as error:
        routes.static_asset(name)
    assert error.value.status_code == 404


def test_static_symlink_escape_rejected(tmp_path, monkeypatch):
    static = tmp_path / 'static'
    static.mkdir()
    secret = tmp_path / 'outside.txt'
    secret.write_text('outside static root')
    try:
        (static / 'escape.txt').symlink_to(secret)
    except OSError:
        pytest.skip('Windows runner does not grant symlink permission')
    monkeypatch.setattr(routes, 'STATIC', static)
    with pytest.raises(HTTPException):
        routes.static_asset('escape.txt')


def test_release_notes_without_project():
    with client() as http:
        data = http.get('/api/v9/release-notes').json()
    assert data['release_id'] == '9.4.1'
    assert data['version'] == '9.4.1'
    assert len(data['notes']) >= 4


def test_both_shells_share_fieldbook_presentation():
    for relative in ('surveysync/static/index.html', 'fieldbook_sync/static/index.html'):
        html = (ROOT / relative).read_text(encoding='utf-8')
        assert '/surveysync-static/fieldbook-standard.css?v=9.4.1' in html
    css = (ROOT / 'surveysync/static/fieldbook-standard.css').read_text(encoding='utf-8')
    assert '.surveysync-workspace' in css
    assert '--panel:#1b1f24' in css
    assert '.brand-lockup-name' in css


def test_brand_generator_preserves_source_and_decodes_every_bitmap(tmp_path):
    spec = importlib.util.spec_from_file_location('brand_assets', ROOT / 'scripts/generate_brand_assets.py')
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    for name in ('branding', 'surveysync/static', 'installer'):
        (tmp_path / name).mkdir(parents=True)
    source = ROOT / 'branding/SurveySync_globe_512.png'
    copy = tmp_path / 'branding/SurveySync_globe_512.png'
    copy.write_bytes(source.read_bytes())
    outputs = generator.generate(tmp_path)
    assert copy.read_bytes() == source.read_bytes()
    assert len(outputs) == 10
    transparent = Image.open(tmp_path / 'branding/SurveySync_globe_transparent_512.png')
    assert transparent.mode == 'RGBA'
    assert transparent.getpixel((0, 0))[3] == 0
    assert transparent.getpixel((256, 256))[3] == 255
    for scale, suffix in ((1, ''), (2, '_200'), (4, '_400')):
        for kind, dims in (('large', (164, 314)), ('small', (55, 55))):
            path = tmp_path / f'installer/wizard_{kind}{suffix}.bmp'
            with Image.open(path) as image:
                image.load()
                assert image.mode == 'RGB'
                assert image.size == (dims[0] * scale, dims[1] * scale)
    raw = (tmp_path / 'branding/SurveySync.ico').read_bytes()
    assert struct.unpack('<HHH', raw[:6]) == (0, 1, 7)
    with Image.open(tmp_path / 'branding/SurveySync.ico') as icon:
        for size in generator.SIZES:
            assert icon.ico.getimage(size).size == size
