param(
  [string]$OutputPath = (Join-Path $PSScriptRoot '..\branding\SurveySync.ico'),
  [string]$SourcePath = (Join-Path $PSScriptRoot '..\branding\SurveySync_globe_512.png')
)

$ErrorActionPreference = 'Stop'
# Generate all web and wizard assets from the same canonical globe.
& python (Join-Path $PSScriptRoot 'generate_brand_assets.py')
if ($LASTEXITCODE -ne 0) { throw 'SurveySync brand asset generation failed.' }
$canonicalSource = Join-Path $PSScriptRoot '..\branding\SurveySync_globe_512.png'
if ([System.IO.Path]::GetFullPath($SourcePath) -eq [System.IO.Path]::GetFullPath($canonicalSource)) {
    $SourcePath = Join-Path $PSScriptRoot '..\branding\SurveySync_globe_transparent_512.png'
}

Add-Type -AssemblyName System.Drawing

if (-not (Test-Path $SourcePath)) {
    throw "SurveySync globe source artwork not found: $SourcePath"
}

$source = [System.Drawing.Image]::FromFile((Resolve-Path $SourcePath))
try {
    function New-GlobePng([int]$Size) {
        $bmp = [System.Drawing.Bitmap]::new(
            $Size,
            $Size,
            [System.Drawing.Imaging.PixelFormat]::Format32bppArgb
        )
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        try {
            $g.Clear([System.Drawing.Color]::Transparent)
            $g.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceOver
            $g.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
            $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
            $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality

            # Fit the canonical globe artwork inside a square without distorting it.
            $pad = [Math]::Max(0, [int][Math]::Round($Size * 0.02))
            $available = $Size - (2 * $pad)
            $scale = [Math]::Min(
                $available / [double]$source.Width,
                $available / [double]$source.Height
            )
            $w = [Math]::Max(1, [int][Math]::Round($source.Width * $scale))
            $h = [Math]::Max(1, [int][Math]::Round($source.Height * $scale))
            $x = [int][Math]::Round(($Size - $w) / 2.0)
            $y = [int][Math]::Round(($Size - $h) / 2.0)

            $g.DrawImage($source, $x, $y, $w, $h)

            $ms = [System.IO.MemoryStream]::new()
            try {
                $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
                return $ms.ToArray()
            }
            finally {
                $ms.Dispose()
            }
        }
        finally {
            $g.Dispose()
            $bmp.Dispose()
        }
    }

    $sizes = @(16,24,32,48,64,128,256)
    $images = foreach($s in $sizes){
        [PSCustomObject]@{ Size=$s; Bytes=[byte[]](New-GlobePng $s) }
    }

    $dir = Split-Path -Parent $OutputPath
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $fs = [System.IO.File]::Open($OutputPath,[System.IO.FileMode]::Create)
    $bw = [System.IO.BinaryWriter]::new($fs)
    try {
        $bw.Write([UInt16]0)
        $bw.Write([UInt16]1)
        $bw.Write([UInt16]$images.Count)
        $offset = 6 + 16 * $images.Count

        foreach($img in $images){
            $wh = if($img.Size -ge 256){0}else{$img.Size}
            $bw.Write([Byte]$wh)
            $bw.Write([Byte]$wh)
            $bw.Write([Byte]0)
            $bw.Write([Byte]0)
            $bw.Write([UInt16]1)
            $bw.Write([UInt16]32)
            $bw.Write([UInt32]$img.Bytes.Length)
            $bw.Write([UInt32]$offset)
            $offset += $img.Bytes.Length
        }

        foreach($img in $images){
            [byte[]]$payload = $img.Bytes
            $bw.Write($payload,0,$payload.Length)
        }
    }
    finally {
        $bw.Dispose()
        $fs.Dispose()
    }

    $final = Get-Item $OutputPath
    Write-Host "Generated SurveySync globe icon: $OutputPath ($($final.Length) bytes, $($images.Count) frames)"
}
finally {
    $source.Dispose()
}
