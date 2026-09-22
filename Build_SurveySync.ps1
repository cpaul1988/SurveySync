param(
    [switch]$SkipLauncherBuild,
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
if ($SkipLauncherBuild) { throw 'Release builds must rebuild both native launchers.' }
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Version = (Get-Content (Join-Path $Root 'VERSION.txt') -Raw).Trim()
$InstallerScript = Join-Path $Root 'installer\SurveySync.iss'
$Output = Join-Path $Root ("installer\output\SurveySync_Setup_{0}.exe" -f $Version)

Write-Host "SurveySync $Version Windows build" -ForegroundColor Cyan

if ($SkipTests) { throw 'Release checks cannot be skipped. Run scripts/release_gate.py to diagnose a failure.' }
$python = Get-Command python -ErrorAction Stop
Push-Location $Root
try {
    & $python.Source .\scripts\release_gate.py
    if ($LASTEXITCODE -ne 0) { throw 'Release quality gate failed. See the failed check above.' }
}
finally { Pop-Location }

if (-not $SkipLauncherBuild) {
    $go = Get-Command go -ErrorAction SilentlyContinue
    if ($go) {
        Push-Location $Root
        try {
            $oldGoos=$env:GOOS; $oldGoarch=$env:GOARCH; $oldCgo=$env:CGO_ENABLED
            $env:GOOS='windows'; $env:GOARCH='amd64'; $env:CGO_ENABLED='0'
            & $go.Source build -trimpath -ldflags '-s -w -H=windowsgui' -o SurveySync.exe .\installer\app_launcher.go
            if ($LASTEXITCODE -ne 0) { throw 'SurveySync.exe build failed.' }
            & $go.Source build -trimpath -ldflags '-s -w -H=windowsgui' -o SurveySyncUpdater.exe .\installer\update_helper.go
            if ($LASTEXITCODE -ne 0) { throw 'SurveySyncUpdater.exe build failed.' }
            $env:GOOS=$oldGoos; $env:GOARCH=$oldGoarch; $env:CGO_ENABLED=$oldCgo
        }
        finally { $env:GOOS=$oldGoos; $env:GOARCH=$oldGoarch; $env:CGO_ENABLED=$oldCgo; Pop-Location }
    }
    else { throw 'Go is required to rebuild the current launchers. Stale prebuilt binaries cannot be released.' }
}

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
    & $Iscc $InstallerScript
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup compile failed with exit code $LASTEXITCODE." }
}
finally { Pop-Location }

if (-not (Test-Path $Output)) { throw "Installer was not created: $Output" }
$hash = (Get-FileHash $Output -Algorithm SHA256).Hash.ToLowerInvariant()
$hashPath = "$Output.sha256"
"$hash  $(Split-Path -Leaf $Output)" | Set-Content -Encoding ascii $hashPath
Write-Host "Built: $Output" -ForegroundColor Green
Write-Host "SHA-256: $hash"
