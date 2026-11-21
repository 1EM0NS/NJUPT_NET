# Renders the title bar icon. The WPF-UI TitleBar template hard-codes the icon
# slot to 16 DIP, so this variant uses bolder rings that survive at 16-20 px.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File tools\make-titlebar-icon.ps1

param(
    [string]$OutFile = (Join-Path $PSScriptRoot '..\Resources\app-icon-titlebar.png'),
    [int]$Size = 64,
    [single]$RadiusK = 0.200,
    [single]$StrokeK = 0.115,
    [single]$OffsetK = 0.068,
    [string]$TintHex = 'DCE7FF'
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'icon-lib.ps1')

function New-TitlebarBitmap(
    [int]$size, [single]$rK, [single]$strokeK, [single]$offK, [System.Drawing.Color]$tint) {
    $ss = 8
    $s = [single]($size * $ss)
    $big = [System.Drawing.Bitmap]::new([int]$s, [int]$s, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($big)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $g.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
    $g.Clear([System.Drawing.Color]::Transparent)

    $bgPath = New-SquirclePath 0 0 $s $s ([single]5.0)
    $bg = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 0x2F, 0x6B, 0xFF))
    $g.FillPath($bg, $bgPath)
    $bg.Dispose()
    $bgPath.Dispose()

    $cx = [single]($s * 0.5)
    $cy = [single]($s * 0.5)
    $stroke = [single]($s * $strokeK)
    $r = [single]($s * $rK)
    $off = [single]($s * $offK)
    $d = $r * 2

    $penWhite = New-RingPen ([System.Drawing.Color]::White) $stroke
    $g.DrawArc($penWhite, [System.Drawing.RectangleF]::new($cx - $off - $r, $cy - $r, $d, $d), 120, 240)
    $penWhite.Dispose()

    $penTint = New-RingPen $tint $stroke
    $g.DrawArc($penTint, [System.Drawing.RectangleF]::new($cx + $off - $r, $cy - $r, $d, $d), 300, 240)
    $penTint.Dispose()
    $g.Dispose()

    $out = [System.Drawing.Bitmap]::new($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g2 = [System.Drawing.Graphics]::FromImage($out)
    $g2.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g2.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $g2.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
    $g2.Clear([System.Drawing.Color]::Transparent)
    $g2.DrawImage($big, [System.Drawing.Rectangle]::new(0, 0, $size, $size))
    $g2.Dispose()
    $big.Dispose()
    return $out
}

$tint = [System.Drawing.ColorTranslator]::FromHtml('#' + $TintHex)
$bmp = New-TitlebarBitmap $Size $RadiusK $StrokeK $OffsetK $tint
$bmp.Save($OutFile, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Output "titlebar icon: $OutFile"
