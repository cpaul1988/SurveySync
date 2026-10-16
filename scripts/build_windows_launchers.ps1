param([string]$Root=(Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference='Stop'
$Root=[IO.Path]::GetFullPath($Root)
$go=Get-Command go -ErrorAction Stop
$expected=(Get-Content (Join-Path $Root 'GO_VERSION.txt') -Raw).Trim()
$actual=(& $go.Source env GOVERSION).Trim()
if ($LASTEXITCODE -ne 0 -or $actual -ne "go$expected") { throw "Use the pinned Go $expected toolchain, not $actual." }
$version=(Get-Content (Join-Path $Root 'VERSION.txt') -Raw).Trim()
$release=(Get-Content (Join-Path $Root 'RELEASE_ID.txt') -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$' -or $release -notmatch '^\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?$') { throw 'Invalid version resources.' }
$rc=Get-ChildItem "${env:ProgramFiles(x86)}/Windows Kits/10/bin/*/x64/rc.exe" -File | Sort-Object FullName -Descending | Select-Object -First 1
$vswhere=Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
if (-not $rc -or -not (Test-Path -LiteralPath $vswhere)) { throw 'Microsoft Windows SDK and Visual Studio build tools are required for native resources.' }
$vs=(& $vswhere -latest -products '*' -property installationPath | Select-Object -First 1)
$cvt=Get-ChildItem "$vs/VC/Tools/MSVC/*/bin/Hostx64/x64/cvtres.exe" -File | Sort-Object FullName -Descending | Select-Object -First 1
if (-not $cvt) { throw 'Microsoft cvtres.exe is required.' }
$work=Join-Path $Root 'build/native'
if (Test-Path $work) { Remove-Item -LiteralPath $work -Recurse -Force }
New-Item -ItemType Directory -Force -Path $work | Out-Null
$environment=@{}
foreach ($key in @('GOOS','GOARCH','CGO_ENABLED','GOTOOLCHAIN','GOFLAGS','GOPROXY')) { $environment[$key]=[Environment]::GetEnvironmentVariable($key,'Process') }
$env:GOOS='windows'; $env:GOARCH='amd64'; $env:CGO_ENABLED='0'; $env:GOTOOLCHAIN='local'; $env:GOFLAGS=''; $env:GOPROXY='off'
$records=@()
try {
    $targets=@(
        @{source='app_launcher.go';name='SurveySync.exe';module='launcher';description='SurveySync desktop launcher'},
        @{source='update_helper.go';name='SurveySyncUpdater.exe';module='updater';description='SurveySync verified update helper'}
    )
    foreach ($target in $targets) {
        $dir=Join-Path $work $target.module
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        $source=Join-Path $Root ("installer/"+$target.source)
        Copy-Item -LiteralPath $source -Destination (Join-Path $dir 'main.go')
        Copy-Item -LiteralPath (Join-Path $Root 'branding/SurveySync.ico') -Destination (Join-Path $dir 'app.ico')
        "module surveysync.local/native/$($target.module)`n`ngo $expected`n" | Set-Content -Encoding ascii (Join-Path $dir 'go.mod')
        @"
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <assemblyIdentity type="win32" name="CleverBirdDevelopment.SurveySync.$($target.module)" version="$version.0" processorArchitecture="amd64" />
  <description>$($target.description)</description>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges><requestedExecutionLevel level="asInvoker" uiAccess="false" /></requestedPrivileges></security></trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1"><application><supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}" /></application></compatibility>
</assembly>
"@ | Set-Content -Encoding utf8 (Join-Path $dir 'app.manifest')
        $numeric=$version.Replace('.',',')+',0'
        @"
LANGUAGE 9,1
1 ICON "app.ico"
1 24 "app.manifest"
1 VERSIONINFO
FILEVERSION $numeric
PRODUCTVERSION $numeric
FILEFLAGSMASK 0x3fL
FILEFLAGS 0
FILEOS 0x40004L
FILETYPE 1
FILESUBTYPE 0
BEGIN
 BLOCK "StringFileInfo"
 BEGIN
  BLOCK "040904b0"
  BEGIN
   VALUE "CompanyName", "Clever Bird Development\0"
   VALUE "FileDescription", "$($target.description)\0"
   VALUE "FileVersion", "$release\0"
   VALUE "InternalName", "$($target.module)\0"
   VALUE "OriginalFilename", "$($target.name)\0"
   VALUE "ProductName", "SurveySync\0"
   VALUE "ProductVersion", "$release\0"
  END
 END
 BLOCK "VarFileInfo"
 BEGIN
  VALUE "Translation", 0x409, 1200
 END
END
"@ | Set-Content -Encoding ascii (Join-Path $dir 'app.rc')
        Push-Location $dir
        try {
            & $rc.FullName /nologo /fo app.res app.rc
            if ($LASTEXITCODE -ne 0) { throw 'Resource compilation failed.' }
            & $cvt.FullName /NOLOGO /MACHINE:X64 /OUT:rsrc_windows_amd64.syso app.res
            if ($LASTEXITCODE -ne 0) { throw 'Resource object conversion failed.' }
            # Keep symbol/debug metadata for diagnostics; do not strip or pack.
            & $go.Source build -trimpath -buildvcs=false -ldflags '-H=windowsgui' -o (Join-Path $Root $target.name) .
            if ($LASTEXITCODE -ne 0) { throw "Native build failed: $($target.name)" }
        } finally { Pop-Location }
        $output=Join-Path $Root $target.name
        $sha=(Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant()
        $info=[Diagnostics.FileVersionInfo]::GetVersionInfo($output)
        if ($info.ProductName -ne 'SurveySync' -or $info.CompanyName -ne 'Clever Bird Development' -or $info.FileVersion -ne $release) { throw 'Embedded native product/version resources are missing.' }
        $buildInfo=(& $go.Source version -m $output | Out-String)
        if ($LASTEXITCODE -ne 0 -or $buildInfo -notmatch [regex]::Escape("go$expected")) { throw 'Native build provenance not available.' }
        $buildInfo | Set-Content -Encoding utf8 (Join-Path $work ($target.name+'.buildinfo.txt'))
        $records+=@{name=$target.name;sha256_unsigned=$sha;source_sha256=(Get-FileHash $source -Algorithm SHA256).Hash.ToLowerInvariant();go_version=$actual;file_version=$info.FileVersion;company=$info.CompanyName;resource_compiler=$rc.FullName}
    }
    $records | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $work 'native-provenance.json')
} finally {
    foreach ($key in $environment.Keys) { [Environment]::SetEnvironmentVariable($key,$environment[$key],'Process') }
}
