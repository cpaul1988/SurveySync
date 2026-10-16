param(
    [switch]$SkipLauncherBuild,
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $Root 'scripts\generate_surveysync_icon.ps1')
if ($SkipLauncherBuild) { throw 'Release builds must rebuild both native launchers.' }
$Version = (Get-Content (Join-Path $Root 'VERSION.txt') -Raw).Trim()
$ReleaseID = (Get-Content (Join-Path $Root 'RELEASE_ID.txt') -Raw).Trim()
$InstallerScript = Join-Path $Root 'installer\SurveySync.iss'
$Output = Join-Path $Root ("installer\output\SurveySync_Setup_{0}.exe" -f $ReleaseID)

Write-Host "SurveySync $ReleaseID Windows build" -ForegroundColor Cyan

if ($SkipTests) { throw 'Release checks cannot be skipped. Run scripts/release_gate.py to diagnose a failure.' }
$python = Get-Command python -ErrorAction Stop
Push-Location $Root
try {
    & $python.Source .\scripts\release_gate.py
    if ($LASTEXITCODE -ne 0) { throw 'Release quality gate failed. See the failed check above.' }
}
finally { Pop-Location }

& (Join-Path $Root 'scripts\build_windows_launchers.ps1') -Root $Root

& (Join-Path $Root 'scripts\sign_windows_artifacts.ps1') -Paths @((Join-Path $Root 'SurveySync.exe'), (Join-Path $Root 'SurveySyncUpdater.exe'))

& (Join-Path $Root 'scripts\scan_windows_artifacts.ps1') -Paths @((Join-Path $Root 'SurveySync.exe'), (Join-Path $Root 'SurveySyncUpdater.exe')) -EvidenceDirectory (Join-Path $Root 'security-evidence/native')

& $python.Source (Join-Path $Root 'scripts\verify_native.py')
if ($LASTEXITCODE -ne 0) { throw 'Native launcher verification failed.' }

$candidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
) | Where-Object { $_ -and (Test-Path $_) }

if (-not $candidates) {
    throw 'Inno Setup 6 (ISCC.exe) was not found. Install Inno Setup 6, then rerun Build_SurveySync.ps1.'
}

$Iscc = @($candidates)[0]
Push-Location (Join-Path $Root 'installer')
try {
    & $Iscc "/DMyReleaseID=$ReleaseID" $InstallerScript
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup compile failed with exit code $LASTEXITCODE." }
}
finally { Pop-Location }

if (-not (Test-Path $Output)) { throw "Installer was not created: $Output" }
& (Join-Path $Root 'scripts\sign_windows_artifacts.ps1') -Paths @($Output)
& (Join-Path $Root 'scripts\scan_windows_artifacts.ps1') -Paths @($Output) -EvidenceDirectory (Join-Path $Root 'security-evidence/installer')
$hash = (Get-FileHash $Output -Algorithm SHA256).Hash.ToLowerInvariant()
$hashPath = "$Output.sha256"
"$hash  $(Split-Path -Leaf $Output)" | Set-Content -Encoding ascii $hashPath
Write-Host "Built: $Output" -ForegroundColor Green
Write-Host "SHA-256: $hash"
