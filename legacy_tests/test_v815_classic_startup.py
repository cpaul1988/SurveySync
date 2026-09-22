from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'fieldbook_sync' / 'static' / 'app.js').read_text(encoding='utf-8')
INDEX = (ROOT / 'fieldbook_sync' / 'static' / 'index.html').read_text(encoding='utf-8')


def test_first_launch_is_fieldbook_classic():
    assert 'data-product-theme="classic"' in INDEX
    assert "localStorage.getItem('fbs-product-theme-user-set')==='1'" in INDEX
    assert "?savedProduct:'classic'" in INDEX
    assert "function startupProductTheme()" in JS
    assert "if(localStorage.getItem(PRODUCT_THEME_USER_SET_KEY)!=='1')return 'classic';" in JS
    assert "applyProductTheme(startupProductTheme(),false)" in JS


def test_user_selected_theme_is_explicitly_persisted():
    assert "const PRODUCT_THEME_PREF_KEY='fbs-product-theme';" in JS
    assert "const PRODUCT_THEME_USER_SET_KEY='fbs-product-theme-user-set';" in JS
    assert "localStorage.setItem(PRODUCT_THEME_PREF_KEY,key);localStorage.setItem(PRODUCT_THEME_USER_SET_KEY,'1');" in JS


def test_invalid_or_legacy_theme_falls_back_to_classic():
    assert "return PRODUCT_THEMES[key]?key:'classic';" in JS
    assert "productThemes.includes(savedProduct)?savedProduct:'classic'" in INDEX


def test_reset_preferences_returns_to_unmarked_classic():
    assert "localStorage.removeItem(PRODUCT_THEME_USER_SET_KEY)" in JS
    assert "applyProductTheme('classic',false)" in JS


def test_v816_version_and_cache_busting():
    assert (ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip() == '8.1.21'
    assert '<title>FieldBook Sync v8.1.21</title>' in INDEX
    assert 'styles.css?v=8.1.21' in INDEX
    assert 'app.js?v=8.1.21' in INDEX
