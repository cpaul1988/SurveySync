"""One-time source migration; removed before the candidate is compiled."""
from pathlib import Path
import hashlib
import re

ROOT = Path(__file__).resolve().parents[1]
GLOBE = '/surveysync-static/surveysync_globe.svg'

def read(p): return (ROOT/p).read_text(encoding='utf-8')
def write(p, s): (ROOT/p).write_text(s, encoding='utf-8')
def marks(context='regular', ident=''):
    return (f'<span class="ss-brand-marks ss-brand-{context}" data-ss-brand="{context}">'
            f'<img class="ss-brand-globe"'+(f' id="{ident}"' if ident else '')+f' src="{GLOBE}" alt="SurveySync globe">'
            '<img class="ss-client-logo" src="/static/edsi_mark.png" alt="EDSI" title="EDSI theme">'
            '</span>')

raw = read('fieldbook_sync/static/app.js').encode()
assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == 'a32ff3cf7cf1dae6941945d93c6c9196284d5d80', 'FieldBookSync source changed; review before applying'
for p in ['surveysync/static/index.html','fieldbook_sync/static/index.html']:
    s=read(p).replace('9.4.0-beta.3','9.4.0-beta.4')
    s=s.replace('</head>','  <link rel="stylesheet" href="/surveysync-static/theme-branding.css?v=9.4.0-beta.4">\n</head>',1)
    s=s.replace(f'<img class="brand-globe" src="{GLOBE}" alt="">',marks('compact'))
    if p.startswith('surveysync'):
        s=s.replace(f'<img src="{GLOBE}" alt="" class="product-splash-icon">',marks('splash'))
        s=s.replace(f'<img class="sidebar-globe" src="{GLOBE}" alt="SurveySync globe">',marks('sidebar'))
        s=s.replace(f'<img class="brand-lockup-icon" src="{GLOBE}" alt="">',marks())
        s=s.replace(f'<img src="{GLOBE}" alt="SurveySync">',marks())
    else:
        s=s.replace(f'<img id="startupBrandLogo" src="{GLOBE}" alt="SurveySync">',marks('splash','startupBrandLogo'))
        s=s.replace('<div class="brand-mark" aria-hidden="true"><img id="sideBrandIcon" src="/surveysync-static/workflow-icons/11-fieldsync.svg" alt="" /></div>',marks('sidebar','sideBrandIcon'))
        s=s.replace('<div class="help-icon">i</div><h2>About</h2>',marks()+'<h2>About</h2>')
    write(p,s)
p='fieldbook_sync/static/app.js';s=read(p)
old="const side=$('#sideBrandIcon'),splash=$('#startupBrandLogo');if(side)side.src=meta.icon;if(splash)splash.src=meta.icon;"
assert old in s
s=s.replace(old,'/* Product marks stay globe-based; theme-branding.css alone controls the EDSI companion. */')
write(p,s)
p='surveysync/static/app.js';s=read(p)
s=s.replace(f'<img class="brand-lockup-icon" src="{GLOBE}" alt="">',marks())
s=s.replace("$('#foundationIcon').innerHTML=`<img src=\"${src}\" alt=\"\">`;", "$('#foundationIcon').innerHTML=activeModule==='Home'?`"+marks()+"`:`<img src=\"${src}\" alt=\"\">`;")
write(p,s)
for p in ['surveysync/router.py','tests/test_beta3_ui.py','tests/test_v940_beta2_brand_release_notes.py','scripts/ui_browser_smoke.py']:
    s=read(p).replace('9.4.0-beta.3','9.4.0-beta.4')
    if p=='surveysync/router.py':
        key='SURVEYSYNC_RELEASE_NOTES = ['
        if key not in s: key=re.search(r'^\w+RELEASE_NOTES\s*=\s*\[',s,re.M).group(0)
        s=s.replace(key,key+'\n    "Beta.4 makes EDSI branding theme-only: normal themes show the SurveySync globe alone; EDSI Adaptive, EDSI Dark and EDSI Light show the globe and EDSI logo side by side throughout both shells.",\n    "Switching themes immediately updates headers, sidebars, Home, About and release notes. The Windows icon and installer retain the SurveySync globe; project data and saved theme preferences are unchanged.",',1)
    if p=='scripts/ui_browser_smoke.py':
        s=s.replace('browser = pw.chromium.launch()', "browser = pw.chromium.launch(executable_path=os.getenv('SURVEYSYNC_BROWSER_EXECUTABLE') or None)")
    write(p,s)
p='installer/SurveySync.iss';write(p,read(p).replace('} Beta.3','} Beta.4'))
notes='''## Beta.4 — Theme-only EDSI co-branding

- Non-EDSI themes use the SurveySync globe alone, including FieldBookSync.
- EDSI Adaptive, EDSI Dark and EDSI Light show the EDSI logo beside the globe in both shells: headers, sidebars, Home, splash markup, About and release notes.
- Switching away from an EDSI theme removes the companion immediately; saved preferences and project data are retained.
- Dark-mode client lettering remains readable without changing the globe colors. Windows icons and the installer remain SurveySync-branded.
- Adds live Options-switch, persistence, cross-window, module, dialog and responsive regression coverage. Full release quality gates remain required.

See `docs/THEME_BRANDING.md` for behavior and validation. This is a test candidate, not a Stable release or native-Windows acceptance signoff.
'''
for p in ('RELEASE_NOTES_v9_4_0.md','QA_REPORT_v9_4_0.md','BUILD_9_4_0.md','CHANGELOG.md'):
    first,rest=read(p).split('\n',1);write(p,first+'\n\n'+notes+'\n'+rest)
print('Theme-only branding applied. No project/configuration records, release tags, or Stable artifacts changed.')
