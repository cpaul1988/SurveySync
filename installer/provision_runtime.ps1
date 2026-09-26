param(
    [Parameter(Mandatory=$true)][string]$InstallDir,
    [string]$AppVersion = "9.3.2"
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$DataRoot = Join-Path $env:LOCALAPPDATA "SurveySync"
$LogDir = Join-Path $DataRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir "setup_runtime.log"

function Write-Log([string]$Message) {
    $line = "{0} | {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $Log -Value $line -Encoding UTF8
}

function Fail([string]$Message) {
    Write-Log "ERROR: $Message"
    throw $Message
}


trap {
    try {
        Write-Log "FATAL provisioning error: $($_.Exception.Message)"
        if ($_.InvocationInfo -and $_.InvocationInfo.PositionMessage) {
            Write-Log ("Location: " + ($_.InvocationInfo.PositionMessage -replace "`r?`n", " | "))
        }
    } catch {}
    exit 1
}

function Get-PythonVersion([string]$PythonExe) {
    if (-not $PythonExe -or -not (Test-Path $PythonExe)) { return $null }
    try {
        $ver = & $PythonExe -c "import sys; print('.'.join(map(str,sys.version_info[:3])))" 2>$null
        if ($LASTEXITCODE -eq 0) { return ([string]$ver).Trim() }
    } catch {}
    return $null
}

function Test-CompatiblePythonHome([string]$PythonHome) {
    # Do not name this parameter $Home. PowerShell variable names are
    # case-insensitive, so $Home collides with the built-in read-only $HOME
    # automatic variable on Windows PowerShell 5.1.
    if (-not $PythonHome) { return $false }
    $exe = Join-Path $PythonHome "python.exe"
    $ver = Get-PythonVersion $exe
    return ($ver -and $ver -like "3.12.*")
}

function Find-CompatiblePythonHome([string]$DestinationDir) {
    # Use a normal PowerShell array here instead of List[string].  List.Add()
    # writes its integer return value to the pipeline unless explicitly discarded;
    # that can make the function return an Object[] instead of one path on
    # Windows PowerShell 5.1 and terminate provisioning before the next log line.
    $candidates = @()

    # First prefer the private runtime from an existing FieldBook Sync 8.x install.
    $candidates += (Join-Path $env:LOCALAPPDATA "Programs\FieldBookSync\runtime")
    $candidates += (Join-Path $env:LOCALAPPDATA "Programs\FieldBook Sync\runtime")

    # Common per-user / machine Python 3.12 locations.  Python's bootstrapper
    # can enter maintenance mode if the same patch release is already registered.
    $candidates += (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312")
    if ($env:ProgramFiles) { $candidates += (Join-Path $env:ProgramFiles "Python312") }
    if (${env:ProgramFiles(x86)}) { $candidates += (Join-Path ${env:ProgramFiles(x86)} "Python312") }

    try {
        $py = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($py -and $py.Source) {
            # $HOME is a read-only automatic variable in Windows PowerShell.
            # Use a distinct variable name; PowerShell variables are case-insensitive.
            $pyHome = & $py.Source '-3.12' -c "import os,sys; print(os.path.dirname(sys.executable))" 2>$null
            if ($LASTEXITCODE -eq 0 -and $pyHome) { $candidates += ([string]$pyHome).Trim() }
        }
    } catch {
        Write-Log "Python launcher discovery failed: $($_.Exception.Message)"
    }

    try {
        $python = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($python -and $python.Source) { $candidates += (Split-Path -Parent $python.Source) }
    } catch {
        Write-Log "python.exe discovery failed: $($_.Exception.Message)"
    }

    $seen = @{}
    foreach ($candidate in $candidates) {
        if (-not $candidate) { continue }
        try { $full = [IO.Path]::GetFullPath([string]$candidate) } catch { continue }
        $key = $full.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true

        try {
            $destFull = [IO.Path]::GetFullPath($DestinationDir)
            if ($full.TrimEnd([char]'\') -ieq $destFull.TrimEnd([char]'\')) { continue }
        } catch {}

        $candidateExe = Join-Path $full "python.exe"
        if (Test-Path $candidateExe) {
            $candidateVer = Get-PythonVersion $candidateExe
            Write-Log "Python candidate: $full (version=$candidateVer)"
        }
        if (Test-CompatiblePythonHome $full) { return $full }
    }
    return $null
}

function Copy-CompatiblePythonRuntime([string]$SourceDir, [string]$DestinationDir) {
    if (-not (Test-CompatiblePythonHome $SourceDir)) { return $false }
    Write-Log "Reusing compatible Python 3.12 runtime from $SourceDir"
    if (Test-Path $DestinationDir) {
        Remove-Item -Recurse -Force $DestinationDir
    }
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    Copy-Item -Path (Join-Path $SourceDir '*') -Destination $DestinationDir -Recurse -Force
    $copiedPy = Join-Path $DestinationDir "python.exe"
    $copiedVer = Get-PythonVersion $copiedPy
    if ($copiedVer -and $copiedVer -like "3.12.*") {
        Write-Log "Private Python runtime copied successfully: $copiedVer"
        return $true
    }
    Write-Log "WARNING: copied Python runtime did not validate"
    return $false
}

function Test-TrustedSignature([string]$Path, [string[]]$PublisherFragments) {
    $sig = Get-AuthenticodeSignature -FilePath $Path
    if ($sig.Status -ne 'Valid') { return $false }
    $subject = [string]$sig.SignerCertificate.Subject
    foreach ($fragment in $PublisherFragments) {
        if ($subject -like "*$fragment*") { return $true }
    }
    return $false
}

Write-Log "============================================================"
Write-Log "SurveySync $AppVersion runtime provisioning started"
Write-Log "InstallDir=$InstallDir"

$RuntimeDir = Join-Path $InstallDir "runtime"
$RuntimePy = Join-Path $RuntimeDir "python.exe"
$RuntimePyW = Join-Path $RuntimeDir "pythonw.exe"
$PythonVersion = "3.12.10"
$PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe"
$PythonInstaller = Join-Path $env:TEMP "surveysync-python-$PythonVersion-amd64.exe"

$needPython = $true
if (Test-Path $RuntimePy) {
    $ver = Get-PythonVersion $RuntimePy
    if ($ver -and $ver -like "3.12.*") {
        $needPython = $false
        Write-Log "Existing private Python runtime is compatible: $ver"
    } else {
        Write-Log "Existing private runtime is incompatible or damaged: $ver"
    }
}

if ($needPython) {
    # Migration fast-path: FieldBook Sync 8.x already installed the same private
    # Python family. Copy that runtime into SurveySync before invoking Python's
    # bootstrapper. Without this, python-3.12.x-amd64.exe can enter maintenance
    # mode, return exit code 0, and create nothing at our new TargetDir.
    $existingHome = Find-CompatiblePythonHome $RuntimeDir
    if ($existingHome) {
        if (Copy-CompatiblePythonRuntime $existingHome $RuntimeDir) {
            $needPython = $false
        }
    }
}

if ($needPython) {
    Write-Log "Downloading Python $PythonVersion x64 from python.org"
    if (Test-Path $PythonInstaller) { Remove-Item -Force $PythonInstaller }
    Invoke-WebRequest -UseBasicParsing -Uri $PythonUrl -OutFile $PythonInstaller
    if (-not (Test-TrustedSignature $PythonInstaller @("Python Software Foundation"))) {
        Fail "The downloaded Python installer did not have a valid Python Software Foundation signature."
    }

    if (Test-Path $RuntimeDir) {
        $backup = "$RuntimeDir.backup.$((Get-Date).ToString('yyyyMMdd_HHmmss'))"
        Write-Log "Preserving previous runtime as $backup"
        Move-Item -Force $RuntimeDir $backup
    }
    New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

    $pyInstallArgs = @(
        "/quiet",
        "InstallAllUsers=0",
        "TargetDir=`"$RuntimeDir`"",
        "Include_pip=1",
        "Include_launcher=0",
        "InstallLauncherAllUsers=0",
        "PrependPath=0",
        "Shortcuts=0",
        "Include_test=0",
        "AssociateFiles=0",
        "CompileAll=0",
        "SimpleInstall=1"
    )
    Write-Log "Installing private Python runtime"
    $proc = Start-Process -FilePath $PythonInstaller -ArgumentList $pyInstallArgs -Wait -PassThru -WindowStyle Hidden

    if ($proc.ExitCode -eq 0 -and -not (Test-Path $RuntimePy)) {
        Write-Log "Python bootstrapper returned success but did not populate TargetDir; looking for the registered 3.12 runtime to copy."
        $fallbackHome = Find-CompatiblePythonHome $RuntimeDir
        if ($fallbackHome) {
            [void](Copy-CompatiblePythonRuntime $fallbackHome $RuntimeDir)
        }
    }

    if ($proc.ExitCode -ne 0) {
        Fail "Python bootstrapper failed with exit code $($proc.ExitCode)."
    }
    if (-not (Test-Path $RuntimePy)) {
        Fail "Python bootstrapper returned exit code 0 but did not create the requested private runtime, and no compatible Python 3.12 runtime could be recovered."
    }
    $installedVer = Get-PythonVersion $RuntimePy
    if (-not $installedVer -or $installedVer -notlike "3.12.*") {
        Fail "The private Python runtime did not validate after installation."
    }
    Write-Log "Private Python runtime installed: $installedVer"
}

# Create/update the application virtual environment from the private runtime.
$VenvDir = Join-Path $InstallDir ".venv"
$VenvPy = Join-Path $VenvDir "Scripts\python.exe"
$VenvPyW = Join-Path $VenvDir "Scripts\pythonw.exe"

$rebuildVenv = $false
if (Test-Path $VenvPy) {
    try {
        $vver = & $VenvPy -c "import sys; print('.'.join(map(str,sys.version_info[:2])))" 2>$null
        if ($LASTEXITCODE -ne 0 -or $vver -ne "3.12") { $rebuildVenv = $true }
    } catch { $rebuildVenv = $true }
}
if ($rebuildVenv) {
    $vbackup = "$VenvDir.backup.$((Get-Date).ToString('yyyyMMdd_HHmmss'))"
    Write-Log "Preserving incompatible app environment as $vbackup"
    Move-Item -Force $VenvDir $vbackup
}
if (-not (Test-Path $VenvPy)) {
    Write-Log "Creating application virtual environment"
    & $RuntimePy -m venv $VenvDir *>> $Log
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPy)) { Fail "Could not create the application virtual environment." }
}

Write-Log "Updating pip in application environment"
& $VenvPy -m pip install --disable-pip-version-check --upgrade pip *>> $Log
if ($LASTEXITCODE -ne 0) { Fail "pip upgrade failed. See $Log" }

$Req = Join-Path $InstallDir "requirements.lock"
Write-Log "Installing SurveySync application dependencies"
& $VenvPy -m pip install --disable-pip-version-check --require-hashes -r $Req *>> $Log
if ($LASTEXITCODE -ne 0) { Fail "Application dependency installation failed. See $Log" }

# Microsoft local AI support is optional. A package/runtime mismatch must never make
# SurveySync itself un-installable. Automatic mode will simply fall through to the
# existing local engines and show the reason in AI & OCR settings.
$WindowsAiReq = Join-Path $InstallDir "requirements-windows-ai.txt"
if (Test-Path $WindowsAiReq) {
    Write-Log "Installing optional Windows AI / Microsoft Foundry Local integration (best effort)"
    & $VenvPy -m pip install --disable-pip-version-check -r $WindowsAiReq *>> $Log
    if ($LASTEXITCODE -ne 0) {
        Write-Log "WARNING: Optional Microsoft local AI packages could not be installed. SurveySync will use its existing local fallback stack."
    } else {
        Write-Log "Optional Microsoft local AI packages installed."
    }
}

Write-Log "Verifying required imports"
$verify = "import fastapi,uvicorn,requests,fitz,PIL,pydantic,webview,numpy,cv2,shapefile,openpyxl,defusedxml; import surveysync.router,fieldbook_sync.app; print('SurveySync production startup imports READY')"
& $VenvPy -c $verify *>> $Log
if ($LASTEXITCODE -ne 0) { Fail "Runtime verification failed. See $Log" }

# Keep bootstrap fingerprint in sync so run_windows.bat does not reinstall on first launch.
$reqBytes = [IO.File]::ReadAllBytes($Req)
$suffixBytes = [Text.Encoding]::UTF8.GetBytes("`nsurveysync-bootstrap-v$AppVersion")
$combined = New-Object byte[] ($reqBytes.Length + $suffixBytes.Length)
[Array]::Copy($reqBytes, 0, $combined, 0, $reqBytes.Length)
[Array]::Copy($suffixBytes, 0, $combined, $reqBytes.Length, $suffixBytes.Length)
$sha = [Security.Cryptography.SHA256]::Create()
try { $hashBytes = $sha.ComputeHash($combined) } finally { $sha.Dispose() }
$hashText = -join ($hashBytes | ForEach-Object { $_.ToString('x2') })
Set-Content -Path (Join-Path $VenvDir ".surveysync_requirements.sha256") -Value $hashText -Encoding ASCII -NoNewline

# WebView2 is normally already installed on Windows 10/11. Attempt a per-user repair only when absent.
$webViewCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} "Microsoft\EdgeWebView\Application"),
    (Join-Path $env:LOCALAPPDATA "Microsoft\EdgeWebView\Application")
) | Where-Object { $_ -and (Test-Path $_) }

if ($webViewCandidates.Count -eq 0) {
    try {
        $wv = Join-Path $env:TEMP "MicrosoftEdgeWebview2Setup.exe"
        Write-Log "WebView2 runtime not detected; downloading Microsoft Evergreen bootstrapper"
        Invoke-WebRequest -UseBasicParsing -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile $wv
        if (Test-TrustedSignature $wv @("Microsoft Corporation", "Microsoft Windows")) {
            $p = Start-Process -FilePath $wv -ArgumentList @('/silent','/install') -Wait -PassThru -WindowStyle Hidden
            Write-Log "WebView2 bootstrapper exit code $($p.ExitCode)"
        } else {
            Write-Log "WARNING: WebView2 bootstrapper signature was not accepted; browser fallback remains available."
        }
    } catch {
        Write-Log "WARNING: WebView2 setup failed: $($_.Exception.Message). Browser fallback remains available."
    }
} else {
    Write-Log "WebView2 runtime detected"
}

$installInfo = [ordered]@{
    product = "SurveySync"
    version = $AppVersion
    publisher = "Clever Bird Development"
    installed_at = (Get-Date).ToString("o")
    install_dir = $InstallDir
    update_provider = "github"
    update_mode = "github_manifest"
    update_manifest_url = ""
    update_release_url = ""
    runtime_python = $PythonVersion
}
$installInfo | ConvertTo-Json -Depth 4 | Set-Content -Path (Join-Path $InstallDir "install_info.json") -Encoding UTF8

Write-Log "SurveySync $AppVersion runtime provisioning completed successfully"
exit 0
