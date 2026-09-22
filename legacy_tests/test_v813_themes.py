from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
INDEX=(ROOT/'fieldbook_sync/static/index.html').read_text(encoding='utf-8')
JS=(ROOT/'fieldbook_sync/static/app.js').read_text(encoding='utf-8')
CSS=(ROOT/'fieldbook_sync/static/styles.css').read_text(encoding='utf-8')

THEMES=['classic','edsi','slate','midnight','lightpro','contrast','carbon','obsidian','teal','violet','graphite','frost','arctic','sandstone','edsidark','edsilight']
ACCENTS=['default','azure','teal','emerald','violet','amber','rose']

def test_v813_all_theme_registry_and_cards_present():
    for key in THEMES:
        assert f"{key}:{{label:" in JS
        assert f'data-theme-choice="{key}"' in INDEX
        assert f'.theme-preview.{key}' in CSS

def test_v813_new_product_tokens_present():
    for key in ['carbon','obsidian','teal','violet','graphite','frost','arctic','sandstone','edsidark','edsilight']:
        assert f'data-product-theme="{key}"' in CSS

def test_v813_accent_selector_and_persistence():
    for key in ACCENTS:
        assert f'data-accent-choice="{key}"' in INDEX
    assert "fbs-accent" in JS
    assert "applyAccent" in JS
    assert 'data-accent="default"' in INDEX

def test_v813_semantic_status_tokens_are_consistent():
    for token in ['--good-soft','--warn-soft','--bad-soft','--info-soft','--good-border','--warn-border','--bad-border','--info-border']:
        assert token in CSS
    assert '.status.YES{color:var(--good);background:var(--good-soft)' in CSS
    assert '.status.NO{color:var(--bad);background:var(--bad-soft)' in CSS
    assert '.status.REVIEW{color:var(--warn);background:var(--warn-soft)' in CSS
    assert '.status.OCR_FOUND{color:var(--info);background:var(--info-soft)' in CSS

def test_v813_edsi_variants_use_official_runtime_logo():
    assert "edsidark:{label:'EDSI Dark',icon:'/static/edsi_mark.png'" in JS
    assert "edsilight:{label:'EDSI Light',icon:'/static/edsi_mark.png'" in JS
    assert 'data-product-theme="edsidark"] .brand-mark img' in CSS
    assert 'data-product-theme="edsilight"] .brand-mark img' in CSS

def test_v813_version_and_cache_busting():
    assert (ROOT/'VERSION.txt').read_text(encoding='utf-8').strip()=='8.1.21'
    assert '<title>FieldBook Sync v8.1.21</title>' in INDEX
    assert 'styles.css?v=8.1.21' in INDEX
    assert 'app.js?v=8.1.21' in INDEX
