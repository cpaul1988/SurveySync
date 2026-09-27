"""Theme-driven branding must not replace the product globe or leak EDSI."""
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from fieldbook_sync.app import app

ROOT = Path(__file__).resolve().parents[1]
GLOBE = '/surveysync-static/surveysync_globe.svg'


class BrandParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []
        self.stylesheets = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'img':
            self.images.append(values)
        if tag == 'link' and values.get('rel') == 'stylesheet':
            self.stylesheets.append(values.get('href', ''))


@pytest.mark.parametrize('relative', ('surveysync/static/index.html', 'fieldbook_sync/static/index.html'))
def test_both_shells_load_shared_branding_after_themes(relative):
    parser = BrandParser()
    parser.feed((ROOT / relative).read_text(encoding='utf-8'))
    assert parser.stylesheets[-1] == '/surveysync-static/theme-branding.css?v=9.4.0-beta.4'
    clients = [image for image in parser.images if image.get('class') == 'ss-client-logo']
    globes = [image for image in parser.images if image.get('class') == 'ss-brand-globe']
    assert len(clients) == len(globes) >= 3
    assert all(image['src'] == GLOBE for image in globes)
    assert all(image['src'] == '/static/edsi_mark.png' and image['alt'] == 'EDSI' for image in clients)


def test_fieldbook_sidebar_and_splash_are_product_globes_not_theme_overrides():
    parser = BrandParser()
    parser.feed((ROOT / 'fieldbook_sync/static/index.html').read_text(encoding='utf-8'))
    for identifier in ('sideBrandIcon', 'startupBrandLogo'):
        image = next(i for i in parser.images if i.get('id') == identifier)
        assert image['src'] == GLOBE
    js = (ROOT / 'fieldbook_sync/static/app.js').read_text(encoding='utf-8')
    assert 'side.src=meta.icon' not in js
    assert 'splash.src=meta.icon' not in js


def test_companion_is_opt_in_for_exact_edsi_theme_names():
    css = (ROOT / 'surveysync/static/theme-branding.css').read_text(encoding='utf-8')
    rule = css.split('.ss-brand-marks>.ss-client-logo{', 1)[1].split('}', 1)[0]
    assert 'display:none' in rule
    for name in ('edsi', 'edsidark', 'edsilight'):
        assert f'[data-product-theme="{name}"]' in css
    assert 'branding_profile' not in css
    assert '.ss-brand-marks>.ss-client-logo{display:block}' in css
    assert 'filter:none' in css


def test_shared_css_and_original_client_artwork_are_served():
    with TestClient(app) as client:
        css = client.get('/surveysync-static/theme-branding.css')
        image = client.get('/static/edsi_mark.png')
    assert css.status_code == 200
    assert css.headers['content-type'].startswith('text/css')
    assert image.status_code == 200
    assert image.content == (ROOT / 'fieldbook_sync/static/edsi_mark.png').read_bytes()


def test_dynamic_product_dialogs_include_the_same_client_component():
    js = (ROOT / 'surveysync/static/app.js').read_text(encoding='utf-8')
    for start, end in (('function openReleaseNotes(', 'function openAboutSurveySync('),
                       ('function openAboutSurveySync(', 'function openGlobalFeedbackWizard(')):
        body = js.split(start, 1)[1].split(end, 1)[0]
        assert 'data-ss-brand="regular"' in body
        assert 'class="ss-client-logo"' in body
        assert GLOBE in body
