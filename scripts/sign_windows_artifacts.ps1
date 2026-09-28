param([Parameter(Mandatory=$true)][string[]]$Paths)
$ErrorActionPreference = 'Stop'
$thumb = ($env:SURVEYSYNC_SIGNING_THUMBPRINT -replace '\s','').ToUpperInvariant()
if (-not $thumb) {
    if ($env:SURVEYSYNC_REQUIRE_SIGNING -eq '1') { throw 'Release signing is required but no certificate is configured.' }
    Write-Host 'UNSIGNED build: Authenticode signing is not configured.'
    return
}
if ($thumb -notmatch '^[A-F0-9]{40}$') { throw 'Invalid signing certificate thumbprint.' }
$cert = Get-Item "Cert:\CurrentUser\My\$thumb" -ErrorAction Stop
if (-not $cert.HasPrivateKey -or $cert.NotAfter -le (Get-Date)) { throw 'Signing certificate is expired or its private key is unavailable.' }
$tool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if (-not $tool) { throw 'Windows SDK signtool.exe is required on the signing runner.' }
$timestamp = $env:SURVEYSYNC_TIMESTAMP_URL
if (-not $timestamp -or ([uri]$timestamp).Scheme -ne 'https') { throw 'Configure an HTTPS RFC3161 timestamp URL.' }
foreach ($path in $Paths) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing signing input: $path" }
    & $tool.Source sign /sha1 $thumb /s My /fd SHA256 /tr $timestamp /td SHA256 $path
    if ($LASTEXITCODE -ne 0) { throw "Authenticode signing failed: $path" }
    & $tool.Source verify /pa /all $path
    if ($LASTEXITCODE -ne 0) { throw "Authenticode chain verification failed: $path" }
    $signature = Get-AuthenticodeSignature -LiteralPath $path
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Thumbprint -ne $thumb -or -not $signature.TimeStamperCertificate) {
        throw "Unexpected signer, timestamp or signature status: $path"
    }
}
