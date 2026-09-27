"""One-time, branch-scoped Beta.3 source migration. Removed after application."""
from pathlib import Path
import re
import tinycss2

ROOT = Path(__file__).resolve().parents[1]

def read(name):
    return (ROOT / name).read_text(encoding='utf-8')

def write(name, text):
    (ROOT / name).write_text(text, encoding='utf-8')

def replace(name, old, new):
    text = read(name)
    assert text.count(old) == 1, (name, old[:80], text.count(old))
    write(name, text.replace(old, new))

replace('surveysync/router.py', 'from . import __version__', 'from . import __version__\nfrom .static_assets import serve_static')
s = read('surveysync/router.py')
a = s.index('@router.get("/surveysync-static/{name}")')
b = s.index('@router.get("/api/v9/status")', a)
s = s[:a] + '@router.get("/surveysync-static/{name:path}")\ndef static_asset(name: str):\n    return serve_static(STATIC, name)\n\n' + s[b:]
s = s.replace('SURVEYSYNC_RELEASE_NOTES_ID = "9.4.0-beta.2"', 'SURVEYSYNC_RELEASE_NOTES_ID = "9.4.0-beta.3"')
a = s.index('    "Beta.2 corrects SurveySync product branding')
b = s.index('    "9.4.0 completes the open-source integration roadmap', a)
s = s[:a] + '''    "Beta.3 makes FieldBookSync the visual standard for Home and every module: shared palettes, toolbars, sidebars, cards, controls, spacing, and readable typography.",
    "Fixes the module-icon startup exception and the static route that rejected workflow-icon subfolders; release notes no longer depend on successful project/status initialization.",
    "Globe branding is generated from one source for application icons and both installer wizard images. Dark-mode wordmarks use light lettering without inverting the globe colors.",
    "Release notes identify this build as 9.4.0-beta.3, remain unread until Continue, and include a visible retry action on failure. Existing project data and saved theme preferences are retained.",
''' + s[b:]
write('surveysync/router.py', s)
s = read('surveysync/integration_routes.py').replace('from .operations_routes import router as operations_router\n', '').replace('router.include_router(operations_router)\n', '')
write('surveysync/integration_routes.py', s)

s = read('surveysync/static/app.js')
s = s.replace("  $('.module-tab[data-module]').forEach(b=>{", "  $$('.module-tab[data-module]').forEach(b=>{")
s = s.replace('    b.prepend(img);', "    img.addEventListener('error',()=>{img.remove();console.warn('Module icon unavailable:',b.dataset.module)},{once:true});\n    b.prepend(img);")
a = s.index('const SS_RELEASE_SEEN_KEY=')
b = s.index('function openAboutSurveySync()', a)
s = s[:a] + read('_ui_payload/release_notes.js') + '\n' + s[b:]
s = s.replace("function switchView(v,label=''){activeView=v;", "function switchView(v,label=''){activeView=v;document.body.dataset.activeView=v;")
s = s.replace("function renderStatus(){const s=statusData,c=s.project,brand=s.branding||{};", "function renderStatus(){const s=statusData,c=s.project,brand=s.branding||{};if($('#workspaceStatusProject'))$('#workspaceStatusProject').textContent='Project: '+(c?.name||'No project open');")
s = s.replace("  if($('#appearanceText'))$('#appearanceText').textContent=label;", "  if($('#appearanceText'))$('#appearanceText').textContent=label;\n  if($('#workspaceAppearance'))$('#workspaceAppearance').textContent=`${glyph} ${label}`;\n  if($('#workspaceStatusTheme'))$('#workspaceStatusTheme').textContent='Theme: '+(THEME_PROFILES[document.documentElement.dataset.productTheme]||'FieldBook Classic');")
s = s.replace("  if($('#appearanceBtn'))$('#appearanceBtn').onclick=cycleAppearance;", "  if($('#appearanceBtn'))$('#appearanceBtn').onclick=cycleAppearance;\n  if($('#workspaceAppearance'))$('#workspaceAppearance').onclick=cycleAppearance;")
s = s.replace('data-nav-index="${i}"><span', 'data-nav-index="${i}" aria-label="${esc(label)}" title="${esc(label)}"><span')
a = s.rindex('applyAppearance(localStorage.getItem(SS_APPEARANCE_KEY)')
b = s.index('\n', a)
assert 'initGlobalThemeControls();applyModuleBrandIcons();' in s[a:b]
s = s[:a] + '''// Independent startup lanes: presentation errors must not suppress release notes.
try{
  applyAppearance(localStorage.getItem(SS_APPEARANCE_KEY)||localStorage.getItem('fbs-theme')||'system',false);
  applyProductTheme(localStorage.getItem(SS_PRODUCT_THEME_KEY)||localStorage.getItem('fbs-product-theme')||'classic',false);
  applyAccent(localStorage.getItem(SS_ACCENT_KEY)||localStorage.getItem('fbs-accent')||'default',false);
}catch(e){console.warn('Stored appearance unavailable',e)}
initGlobalThemeControls();
try{applyModuleBrandIcons()}catch(e){console.warn('Module icons could not be initialized',e)}
const startupParams=new URLSearchParams(location.search),initial=startupParams.get('module');
if(initial&&modules[initial])activeModule=initial;
switchModule(activeModule);
loadReleaseNotes(true);
loadSharedUiPrefs().finally(()=>refresh().then(()=>{
  if(startupParams.get('manage_projects')==='1')showProjectManager();
}).catch(e=>toast(e.message)));
''' + s[b:]
write('surveysync/static/app.js', s)

for name in ('surveysync/static/index.html', 'fieldbook_sync/static/index.html'):
    s = read(name)
    s = s.replace('</head>', '  <link rel="stylesheet" href="/surveysync-static/fieldbook-standard.css?v=9.4.0-beta.3">\n</head>', 1)
    s = s.replace('?v=9.4.0"', '?v=9.4.0-beta.3"')
    body = '<body class="surveysync-workspace" data-active-view="dashboard">' if name.startswith('surveysync') else '<body class="fieldbook-workspace">'
    s = s.replace('<body>', body, 1)
    write(name, s)
s = read('surveysync/static/index.html')
a = s.index('      <header class="workspace-header">')
b = s.index('        <section id="dashboard"', a)
s = s[:a] + read('_ui_payload/workspace_header.html') + s[b:]
s = s.replace('<div class="module-heading">', '<div class="module-heading">\n        <img class="sidebar-globe" src="/surveysync-static/surveysync_globe.svg" alt="SurveySync globe">', 1)
s = s.replace('>CURRENT PROJECT</div>', '>LOCAL WORKSPACE</div>', 1)
metrics = '          <div id="metrics" class="metrics"></div>\n'
assert s.count(metrics) == 1
s = s.replace(metrics, '')
s = s.replace('          <div id="whatsNewCard"', metrics + read('_ui_payload/workflow_cards.html') + '          <div id="whatsNewCard"', 1)
s = s.replace('SURVEYSYNC v9 FOUNDATION', 'ONE CONNECTED SURVEY WORKSPACE', 1)
s = s.replace('<h3>Release infrastructure</h3>', '<h3>Support &amp; updates</h3>', 1)
end = '      </div>\n    </main>\n  </div>\n</div>'
assert s.count(end) == 1
s = s.replace(end, '''      </div>
      <footer class="desktop-statusbar"><span id="workspaceStatusProject">Project: No project open</span><span class="status-spacer"></span><span id="workspaceStatusTheme">Theme: FieldBook Classic</span><span id="workspaceBuild">SurveySync v9.4.0-beta.3</span></footer>
    </main>
  </div>
</div>''')
write('surveysync/static/index.html', s)

# Extract the palettes from the actual FieldBookSync stylesheet; use the same final
# presentation layer in both shells. Preserve every supported theme and accent.
allowed = {'--font','--radius','--radius-sm','--accent','--accent-2','--accent-soft','--good','--warn','--bad','--info','--bg','--panel','--panel2','--panel3','--sidebar-bg','--text','--muted','--muted2','--line','--line2','--input','--hover','--overlay','--glass','--white-soft','--shadow','--shadow-sm','--survey-menubar-bg','--survey-menubar-text'}
allowed.update('--'+a+'-'+b for a in ['good','warn','bad','info'] for b in ['soft','border'])
parts = ['/* Shared presentation: FieldBookSync is the visual reference. */\n']
for rule in tinycss2.parse_stylesheet(read('fieldbook_sync/static/styles.css'), skip_comments=True, skip_whitespace=True):
    if rule.type != 'qualified-rule':
        continue
    sel = tinycss2.serialize(rule.prelude).strip()
    if not re.fullmatch(r'(?:html(?:\[[^\]]+\])*|:root)', sel):
        continue
    declarations = tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True)
    props = [f'{d.name}:{tinycss2.serialize(d.value).strip()}' for d in declarations if d.type == 'declaration' and d.name in allowed]
    if props:
        parts.append(sel + '{' + ';'.join(props) + '}\n')
parts.append(read('_ui_payload/workspace.css'))
write('surveysync/static/fieldbook-standard.css', ''.join(parts))

replace('installer/SurveySync.iss', 'AppVerName={#MyAppName} {#MyAppVersion}', 'AppVerName={#MyAppName} {#MyAppVersion} Beta.3')
replace('installer/SurveySync.iss', 'WizardImageFile=wizard_large.bmp', 'WizardImageFile=wizard_large.bmp,wizard_large_200.bmp,wizard_large_400.bmp')
replace('installer/SurveySync.iss', 'WizardSmallImageFile=wizard_small.bmp', 'WizardSmallImageFile=wizard_small.bmp,wizard_small_200.bmp,wizard_small_400.bmp\nWizardImageStretch=yes')
s = read('scripts/generate_surveysync_icon.ps1')
s = s.replace("$ErrorActionPreference = 'Stop'", r'''$ErrorActionPreference = 'Stop'
# Generate all web and wizard assets from the same canonical globe.
& python (Join-Path $PSScriptRoot 'generate_brand_assets.py')
if ($LASTEXITCODE -ne 0) { throw 'SurveySync brand asset generation failed.' }
$canonicalSource = Join-Path $PSScriptRoot '..\branding\SurveySync_globe_512.png'
if ([System.IO.Path]::GetFullPath($SourcePath) -eq [System.IO.Path]::GetFullPath($canonicalSource)) {
    $SourcePath = Join-Path $PSScriptRoot '..\branding\SurveySync_globe_transparent_512.png'
}
''', 1)
write('scripts/generate_surveysync_icon.ps1', s)
s = read('tests/test_v940_beta2_brand_release_notes.py')
s = s.replace('assert body["release_id"] == "9.4.0-beta.2"', 'assert body["release_id"] == "9.4.0-beta.3"')
a = s.index('    assert "const releaseId=String')
b = s.index('\n\n\ndef test_beta2_all', a)
s = s[:a] + '''    assert "releaseId=String(d.release_id||d.version||'').trim()" in js
    assert "if(markSeen&&releaseId)markNotesSeen(releaseId)" in js
    assert "function notesWereSeen(id)" in js
    assert "localStorage.setItem(SS_RELEASE_SEEN_KEY,id)" in js
    assert "if(markSeen&&version)" not in js
''' + s[b:]
write('tests/test_v940_beta2_brand_release_notes.py', s)
for name in ('RELEASE_NOTES_v9_4_0.md', 'QA_REPORT_v9_4_0.md', 'BUILD_9_4_0.md'):
    first, rest = read(name).split('\n', 1)
    write(name, first + '\n\n' + read('_ui_payload/notes.md') + '\n' + rest)
print('Applied Beta.3 source changes. No project data, release tags, or Stable artifacts modified.')
