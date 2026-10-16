param(
    [Parameter(Mandatory=$true)][string[]]$Paths,
    [Parameter(Mandatory=$true)][string]$EvidenceDirectory
)
# Scan only. Never execute an artifact, change exclusions, restore quarantine,
# suppress detections, or disable a Defender protection feature.
$ErrorActionPreference = 'Stop'
$evidence = [IO.Path]::GetFullPath($EvidenceDirectory)
New-Item -ItemType Directory -Force -Path $evidence | Out-Null
$reportPath = Join-Path $evidence 'security-scan.json'
$report = [ordered]@{
    schema_version=1; result='failed'; started_utc=[DateTime]::UtcNow.ToString('o')
    source_sha=$env:GITHUB_SHA; defender=$null; scans=@(); error=$null
}
function Snapshot {
    $s=Get-MpComputerStatus -ErrorAction Stop
    return [ordered]@{
        AMServiceEnabled=[bool]$s.AMServiceEnabled
        AntivirusEnabled=[bool]$s.AntivirusEnabled
        RealTimeProtectionEnabled=[bool]$s.RealTimeProtectionEnabled
        AMEngineVersion=[string]$s.AMEngineVersion
        AMProductVersion=[string]$s.AMProductVersion
        AntivirusSignatureVersion=[string]$s.AntivirusSignatureVersion
        AntivirusSignatureLastUpdatedUtc=$s.AntivirusSignatureLastUpdated.ToUniversalTime().ToString('o')
    }
}
try {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'Microsoft Defender release scans require Windows.' }
    if (-not (Get-Command Get-MpComputerStatus -ErrorAction SilentlyContinue)) { throw 'Microsoft Defender is unavailable.' }
    & (Join-Path $PSScriptRoot 'initialize_defender.ps1') -EvidenceDirectory $evidence
    $status=Snapshot
    $report.defender=$status
    foreach ($flag in @('AMServiceEnabled','AntivirusEnabled','RealTimeProtectionEnabled')) {
        if (-not $status[$flag]) { throw "Microsoft Defender protection is not active: $flag" }
    }
    $age=[DateTime]::UtcNow-([DateTime]::Parse($status.AntivirusSignatureLastUpdatedUtc).ToUniversalTime())
    if ($age.TotalHours -gt 48 -or $age.TotalMinutes -lt -5) { throw 'Security intelligence is stale or future-dated.' }
    $platform=Get-ChildItem "$env:ProgramData/Microsoft/Windows Defender/Platform" -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
    $mp=if ($platform) { Join-Path $platform.FullName 'MpCmdRun.exe' } else { "$env:ProgramFiles/Windows Defender/MpCmdRun.exe" }
    if (-not (Test-Path -LiteralPath $mp -PathType Leaf)) { throw 'MpCmdRun.exe not found.' }
    $seen=@{}
    foreach ($inputPath in $Paths) {
        $file=Get-Item -LiteralPath $inputPath -ErrorAction Stop
        if ($file.PSIsContainer -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Expected a regular artifact file: $inputPath" }
        if ($seen.ContainsKey($file.Name)) { throw "Duplicate artifact name: $($file.Name)" }
        $seen[$file.Name]=$true
        $before=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $outputName=$file.Name+'.defender.txt'
        $outputPath=Join-Path $evidence $outputName
        # Microsoft documents this custom-scan mode as ignoring file exclusions
        # and including archives. Only this scan's remediation is disabled;
        # real-time protection remains active and can quarantine independently.
        $text=(& $mp -Scan -ScanType 3 -File $file.FullName -DisableRemediation 2>&1 | Out-String)
        $exitCode=$LASTEXITCODE
        [IO.File]::WriteAllText($outputPath,$text,[Text.UTF8Encoding]::new($false))
        $exists=Test-Path -LiteralPath $file.FullName -PathType Leaf
        $after=if ($exists) { (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() } else { '' }
        # Unknown/localized output fails closed instead of being declared clean.
        $noThreats=($exitCode -eq 0 -and $text -match '(?im)^Scanning .+ found no threats\.\s*$')
        $report.scans+= [ordered]@{
            name=$file.Name; size_bytes=$file.Length; sha256_before=$before
            sha256_after=$after; exists_after=[bool]$exists; exit_code=[int]$exitCode
            mode='custom-detection-only'; threat_detected=(-not $noThreats)
            output_file=$outputName
            output_sha256=(Get-FileHash -LiteralPath $outputPath -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        Write-Host $text
        if (-not $noThreats) { throw "Detection, scan error, or unrecognized no-threat output: $($file.Name) (code $exitCode)." }
        if (-not $exists -or $after -ne $before) { throw "Artifact changed or was remediated: $($file.Name)" }
    }
    if ($report.scans.Count -eq 0) { throw 'No artifacts scanned.' }
    $report.defender=Snapshot
    foreach ($flag in @('AMServiceEnabled','AntivirusEnabled','RealTimeProtectionEnabled')) {
        if (-not $report.defender[$flag]) { throw "Protection state changed during scan: $flag" }
    }
    $report.result='passed'
}
catch { $report.error=$_.Exception.Message; throw }
finally {
    $report.completed_utc=[DateTime]::UtcNow.ToString('o')
    $report | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 $reportPath
}
$python=(Get-Command python -ErrorAction Stop).Source
& $python (Join-Path $PSScriptRoot 'validate_security_evidence.py') $reportPath @Paths
if ($LASTEXITCODE -ne 0) { throw 'Security evidence failed independent validation.' }
