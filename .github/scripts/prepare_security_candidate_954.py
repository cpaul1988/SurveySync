"""One-time, preimage-verified packaging migration. Never writes release feeds."""
from pathlib import Path
import hashlib
import json

ROOT=Path(__file__).resolve().parents[2]
PREIMAGES={
 'VERSION.txt':'6d9fe7577856901b0b632c80ced7625bd7bf4ec30170dedff3d0e47efc2c7b55',
 'RELEASE_ID.txt':'722d325181a63d3bc423fe6fa812670b63b69f54325f6fda9ad583a49222178c',
 'surveysync/__init__.py':'50cbeaab13736b62579f415f1acfc2210bae96344174b28cc69996a5dd5741d2',
 'installer/app_launcher.go':'33de595dfa85e4c5b9d7dd2961b1be02ed1b2be9bda7ac72356e358353236a6d',
 'installer/SurveySync.iss':'a2bea4416724be4a1a9b201cbcee010226b8f6bdd3430abba53a1d1cdcf2186c',
 'installer/provision_runtime.ps1':'8bbf6c7a59eb826e2ad5df584b4cfa8be4e45a3a1fef4721663f1c2d46a3de4d',
 'surveysync/static/index.html':'2aa8abe9597e6da133ad2476833ba2008759fa102841327a59f96cda4fda3c33',
 'fieldbook_sync/static/index.html':'16831bf85cf7b3675f8a9e2ce2b5ba234ce03344f6a49a451f5a93b88db7b265',
 'surveysync/static/app.js':'9460226882b6a93e6f1d1d0f5afa7f671135da88013754210de980aff70c9b3a',
 'surveysync/router.py':'03f67e51af5a6e8efad31126a9ddf1a708a5101aa250eb06384b2133e8aa4f14',
 'Build_SurveySync.ps1':'67629ff402d9ef13b8d2bc01fc4f5a856326db2405638ab2a03245aae92cf4d6',
 '.github/workflows/ui-validation.yml':'d37cc5e5c4316e908ca85f959565833d317d11e298b6086f113a995311a993ac',
 '.github/workflows/release.yml':'fb28c3609d4da3a967c54f8a481e81e8f8489993ac536cd7e0dd93328d1a35bb',
 '.github/workflows/remaining-audit.yml':'371843f03e0f709f6e5f897b63a52cec29818e3ce222c8c08296f895202a161f',
 '.github/workflows/repair-acceptance.yml':'4dc5e1e3b6942a0642536ebc806cb34829b9a38fac953fb117e204c4695a7e8f',
 'surveysync/updater.py':'5d2b5bef7e68fabf3e852b44104c4b0ba5f4fe7bd6ccfd9003eec3d39b5eb7d8',
 'tests/test_v9_native_launcher_subsystem.py':'fa7ab6397926d76de52b7173c55f65da77e9fd149d3d54efa71b91b4ae9d2537',
 'BUILD_MANIFEST.json':'82c116fb988db14289a4028687ba375134bc9acaaf666c5137b5abc43f8c6585',
 'IMPLEMENTATION_INDEX.json':'e598be2c06c59e7f8e655e941724f24499ef29f9923a68201ee56d1fdbb1890f',
 'CHANGELOG.md':'f5d4e5b6dc1794f77514ab752d47a43bdfa95530fc1c234142b170a6d7619530'
}

def replace(text,before,after,count=1):
    if text.count(before)!=count: raise ValueError('Unexpected exact replacement count: '+before[:70])
    return text.replace(before,after)

def main(root=ROOT):
    staged={}
    for name,digest in PREIMAGES.items():
        data=(root/name).read_bytes()
        if hashlib.sha256(data).hexdigest()!=digest: raise ValueError('Preimage changed; refusing patch: '+name)
        staged[name]=data.decode('utf-8')
    for name in list(PREIMAGES)[:10]:
        if '9.5.3' not in staged[name]: raise ValueError('Version marker missing: '+name)
        staged[name]=staged[name].replace('9.5.3','9.5.4')
    build=staged['Build_SurveySync.ps1']
    start=build.index('if (-not $SkipLauncherBuild) {')
    end=build.index("& (Join-Path $Root 'scripts\\sign_windows_artifacts.ps1')",start)
    build=build[:start]+"& (Join-Path $Root 'scripts\\build_windows_launchers.ps1') -Root $Root\n\n"+build[end:]
    native="& (Join-Path $Root 'scripts\\scan_windows_artifacts.ps1') -Paths @((Join-Path $Root 'SurveySync.exe'), (Join-Path $Root 'SurveySyncUpdater.exe')) -EvidenceDirectory (Join-Path $Root 'security-evidence/native')\n\n"
    setup="& (Join-Path $Root 'scripts\\scan_windows_artifacts.ps1') -Paths @($Output) -EvidenceDirectory (Join-Path $Root 'security-evidence/installer')\n"
    before="& $python.Source (Join-Path $Root 'scripts\\verify_native.py')"
    build=replace(build,before,native+before)
    before="$hash = (Get-FileHash $Output -Algorithm SHA256).Hash.ToLowerInvariant()"
    staged['Build_SurveySync.ps1']=replace(build,before,setup+before)
    for name in PREIMAGES:
        if not name.startswith('.github/workflows/'): continue
        text=staged[name]; n=text.count("go-version: '1.23.x'")
        if n<1: raise ValueError('No old toolchain in '+name)
        text=replace(text,"go-version: '1.23.x'","go-version: '1.27.2'",n)
        if './Build_SurveySync.ps1' in text:
            before='      - uses: actions/setup-go@v5'
            enable="      - name: Require active Defender for release artifact scans\n        shell: pwsh\n        run: |\n          if ((Get-Service WinDefend).Status -ne 'Running') { Start-Service WinDefend }\n          Set-MpPreference -DisableRealtimeMonitoring $false -ErrorAction Stop\n          Update-MpSignature -ErrorAction Stop\n"
            text=replace(text,before,enable+before,text.count(before))
        staged[name]=text
    staged['installer/SurveySync.iss']=replace(staged['installer/SurveySync.iss'],'Excludes: "','Excludes: "security-evidence\\*,original-input\\*,original-unpacked\\*,')
    before='    channels = manifest.get("channels")'
    after='''    hold = manifest.get("release_hold")
    if isinstance(hold, dict) and hold.get("active") is True:
        held = hold.get("channels", [])
        if not isinstance(held, list) or channel in held:
            raise ValueError("SurveySync updates are temporarily suspended for security review. Keep Windows protection enabled.")
    channels = manifest.get("channels")'''
    staged['surveysync/updater.py']=replace(staged['surveysync/updater.py'],before,after)
    test=staged['tests/test_v9_native_launcher_subsystem.py']; pos=test.index('    lines = [line.strip()')
    staged['tests/test_v9_native_launcher_subsystem.py']=test[:pos]+'''    assert "scripts\\\\build_windows_launchers.ps1" in build
    helper = (ROOT / "scripts/build_windows_launchers.ps1").read_text(encoding="utf-8")
    assert "source='app_launcher.go'" in helper
    assert "source='update_helper.go'" in helper
    lines = [line for line in helper.splitlines() if "& $go.Source build" in line]
    assert len(lines) == 1 and "-H=windowsgui" in lines[0]
    assert "GOTOOLCHAIN='local'" in helper
    assert "GO_VERSION.txt" in helper
'''
    manifest=json.loads(staged['BUILD_MANIFEST.json'])
    manifest.update(version='9.5.4',release_id='9.5.4-beta.1',build_type='security-release-candidate',baseline='9.5.3 + Defender incident containment',candidate_branch='fix/defender-release-954')
    manifest['feedback']={'checked_before_build':True,'checked_utc':'2026-10-16','intake_count':18,'latest_intake':'FBR-0018','notes':'Intake rechecked before this candidate build. Defender screenshots and explicit fix request are the security incident input. FieldBook integration is retained.'}
    manifest['qa']={'status':'Security evidence and independent Windows acceptance required. No claim of vendor false-positive clearance.','coverage_floor_percent':54}
    manifest['security']={'defender_required':True,'go_version':'1.27.2','blocked_release':'9.5.3-beta.1','vendor_clearance':False}
    staged['BUILD_MANIFEST.json']=json.dumps(manifest,indent=2)+'\n'
    index=json.loads(staged['IMPLEMENTATION_INDEX.json']);index['version']='9.5.4'
    index['features']['security_artifact_gate']={'introduced':'9.5.4','implementation':['scripts/scan_windows_artifacts.ps1','scripts/validate_security_evidence.py','scripts/build_windows_launchers.ps1'],'tests':['tests/test_security_evidence.py'],'documentation':['docs/SECURITY_INCIDENT_953.md','RELEASE_NOTES_v9_5_4.md']}
    staged['IMPLEMENTATION_INDEX.json']=json.dumps(index,indent=2)+'\n'
    router=staged['surveysync/router.py'];start=router.index('SURVEYSYNC_RELEASE_NOTES = [');end=router.index('\n]',start)+2
    notes=['9.5.4-beta.1 adds native build provenance and mandatory artifact security scanning.', 'Launchers use pinned Go 1.27.2 and embed SurveySync product/version/icon resources.', 'Active, freshly updated Microsoft Defender must scan the signed launchers and final installer.', 'Artifact hashes and scanner logs are retained and checked before packaging or release.', 'FBR-0018 project identity, shared themes and persistent FieldBook module switching are retained.', 'Security holds fail closed. A scan pass is not a Microsoft false-positive determination.']
    staged['surveysync/router.py']=router[:start]+'SURVEYSYNC_RELEASE_NOTES = '+json.dumps(notes,indent=4)+router[end:]
    staged['CHANGELOG.md']='# 9.5.4-beta.1 — security build hardening\n\nPinned supported Go toolchain, native product resources, mandatory active Defender scans of signed launchers and final installer, hash-bound scan evidence, and clear update-hold errors. Retains FBR-0018. Release remains held pending independent acceptance; this is not a Microsoft false-positive determination.\n\n'+staged['CHANGELOG.md']
    for name,text in staged.items(): (root/name).write_bytes(text.encode('utf-8'))
    return sorted(staged)

if __name__=='__main__': print('Updated controlled files:',*main(),sep='\n')
