param(
  [string]$OutputPath = (Join-Path $PSScriptRoot '..\branding\SurveySync.ico')
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$navy = [System.Drawing.ColorTranslator]::FromHtml('#0F203C')
$navyLight = [System.Drawing.ColorTranslator]::FromHtml('#1A3358')
$gold = [System.Drawing.ColorTranslator]::FromHtml('#C19D65')
$cream = [System.Drawing.ColorTranslator]::FromHtml('#F6F4EE')

function New-BrandPng([int]$Size) {
    $bmp = [System.Drawing.Bitmap]::new($Size,$Size,[System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    try {
        $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $g.Clear([System.Drawing.Color]::Transparent)

        $radius = [Math]::Max(2,[int]($Size * .18))
        $path = [System.Drawing.Drawing2D.GraphicsPath]::new()
        $d = $radius * 2
        $path.AddArc(0,0,$d,$d,180,90)
        $path.AddArc($Size-$d,0,$d,$d,270,90)
        $path.AddArc($Size-$d,$Size-$d,$d,$d,0,90)
        $path.AddArc(0,$Size-$d,$d,$d,90,90)
        $path.CloseFigure()
        $navyBrush = [System.Drawing.SolidBrush]::new($navy)`n        $g.FillPath($navyBrush,$path)

        $margin = $Size * .16
        $diam = $Size - 2*$margin
        $penGold = [System.Drawing.Pen]::new($gold,[single][Math]::Max(1,$Size*.028))
        $penLight = [System.Drawing.Pen]::new($navyLight,[single][Math]::Max(1,$Size*.02))
        $g.DrawEllipse($penGold,$margin,$margin,$diam,$diam)

        foreach($f in @(.36,.48,.60,.72)){
          $y=$Size*$f
          $h=[Math]::Max(2,$Size*.08)
          $g.DrawArc($penLight,$margin,$y-$h/2,$diam,$h,0,180)
        }
        foreach($f in @(.36,.50,.64)){
          $x=$Size*$f
          $w=[Math]::Max(2,$Size*.16)
          $g.DrawArc($penGold,$x-$w/2,$margin,$w,$diam,90,180)
        }

        $fontSize=[Math]::Max(8,$Size*.38)
        $font=[System.Drawing.Font]::new('Georgia',[single]$fontSize,[System.Drawing.FontStyle]::Bold,[System.Drawing.GraphicsUnit]::Pixel)
        $sf=[System.Drawing.StringFormat]::new()
        $sf.Alignment=[System.Drawing.StringAlignment]::Center
        $sf.LineAlignment=[System.Drawing.StringAlignment]::Center
        $creamBrush=[System.Drawing.SolidBrush]::new($cream)`n        $g.DrawString('S',$font,$creamBrush,[System.Drawing.RectangleF]::new(0,0,$Size,$Size),$sf)

        $starX=$Size*.50; $starY=$Size*.10; $r=$Size*.035
        $pts = [System.Drawing.PointF[]]@(
          [System.Drawing.PointF]::new($starX,$starY-$r*1.8),
          [System.Drawing.PointF]::new($starX+$r*.6,$starY-$r*.6),
          [System.Drawing.PointF]::new($starX+$r*1.8,$starY),
          [System.Drawing.PointF]::new($starX+$r*.6,$starY+$r*.6),
          [System.Drawing.PointF]::new($starX,$starY+$r*1.8),
          [System.Drawing.PointF]::new($starX-$r*.6,$starY+$r*.6),
          [System.Drawing.PointF]::new($starX-$r*1.8,$starY),
          [System.Drawing.PointF]::new($starX-$r*.6,$starY-$r*.6)
        )
        $goldBrush=[System.Drawing.SolidBrush]::new($gold)`n        $g.FillPolygon($goldBrush,$pts)

        $ms = [System.IO.MemoryStream]::new()
        $bmp.Save($ms,[System.Drawing.Imaging.ImageFormat]::Png)
        return $ms.ToArray()
    }
    finally {
        if($navyBrush){$navyBrush.Dispose()}
        if($creamBrush){$creamBrush.Dispose()}
        if($goldBrush){$goldBrush.Dispose()}
        if($penGold){$penGold.Dispose()}
        if($penLight){$penLight.Dispose()}
        if($font){$font.Dispose()}
        if($sf){$sf.Dispose()}
        if($path){$path.Dispose()}
        $g.Dispose()
        $bmp.Dispose()
    }
}

$sizes = @(16,24,32,48,64,128,256)
$images = foreach($s in $sizes){ [PSCustomObject]@{ Size=$s; Bytes=(New-BrandPng $s) } }

$dir = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$fs = [System.IO.File]::Open($OutputPath,[System.IO.FileMode]::Create)
$bw = [System.IO.BinaryWriter]::new($fs)
try {
    $bw.Write([UInt16]0); $bw.Write([UInt16]1); $bw.Write([UInt16]$images.Count)
    $offset = 6 + 16 * $images.Count
    foreach($img in $images){
        $wh = if($img.Size -ge 256){0}else{$img.Size}
        $bw.Write([Byte]$wh); $bw.Write([Byte]$wh); $bw.Write([Byte]0); $bw.Write([Byte]0)
        $bw.Write([UInt16]1); $bw.Write([UInt16]32)
        $bw.Write([UInt32]$img.Bytes.Length); $bw.Write([UInt32]$offset)
        $offset += $img.Bytes.Length
    }
    foreach($img in $images){ $bw.Write($img.Bytes) }
}
finally { $bw.Dispose(); $fs.Dispose() }

Write-Host "Generated SurveySync 9.4 brand icon: $OutputPath"
