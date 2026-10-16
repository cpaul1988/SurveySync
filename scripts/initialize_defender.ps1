param(
    [string]$EvidenceDirectory='security-evidence/prepare',
    [switch]$EnableRealtime
)
# Only refresh intelligence and, on an explicitly requested disposable CI host,
# enable protection. Never change exclusions, allow files, or restore quarantine.
$ErrorActionPreference='Stop'
$directory=[IO.Path]::GetFullPath($EvidenceDirectory)
New-Item -ItemType Directory -Force -Path $directory | Out-Null
$attempts=@()
$success=$false
try {
    if (-not (Get-Command Update-MpSignature -ErrorAction SilentlyContinue)) { throw 'Microsoft Defender is unavailable.' }
    if ($EnableRealtime) {
        if ((Get-Service WinDefend -ErrorAction Stop).Status -ne 'Running') { Start-Service WinDefend -ErrorAction Stop }
        Set-MpPreference -DisableRealtimeMonitoring $false -ErrorAction Stop
    }
    # MMPC and MicrosoftUpdateServer are documented Microsoft sources. A failed
    # attempt is recorded and retried, never relabeled as a successful update.
    foreach ($source in @('Default','MMPC','MicrosoftUpdateServer')) {
        try {
            if ($source -eq 'Default') { Update-MpSignature -ErrorAction Stop }
            else { Update-MpSignature -UpdateSource $source -ErrorAction Stop }
            $status=Get-MpComputerStatus -ErrorAction Stop
            if (-not $status.AMServiceEnabled -or -not $status.AntivirusEnabled -or -not $status.RealTimeProtectionEnabled) { throw 'Defender antivirus or real-time protection is inactive.' }
            $age=([DateTime]::UtcNow-$status.AntivirusSignatureLastUpdated.ToUniversalTime()).TotalHours
            if ($age -lt (-5.0/60.0) -or $age -gt 48) { throw 'Updated intelligence is missing, stale, or future-dated.' }
            $attempts+=[ordered]@{source=$source;utc=[DateTime]::UtcNow.ToString('o');success=$true;signature_version=$status.AntivirusSignatureVersion}
            $success=$true
            Write-Host "Defender intelligence ready: $($status.AntivirusSignatureVersion) via $source"
            break
        } catch {
            $attempts+=[ordered]@{source=$source;utc=[DateTime]::UtcNow.ToString('o');success=$false;error=$_.Exception.Message}
            Write-Warning "Defender update via $source failed: $($_.Exception.Message)"
            if ($source -ne 'MicrosoftUpdateServer') { Start-Sleep -Seconds 5 }
        }
    }
    if (-not $success) { throw 'No Microsoft intelligence update source succeeded with fresh, active protection. Release scan remains blocked.' }
} finally {
    [ordered]@{schema_version=1;success=$success;attempts=$attempts;completed_utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json -Depth 6 | Set-Content -Encoding utf8 (Join-Path $directory 'intelligence-update.json')
}
