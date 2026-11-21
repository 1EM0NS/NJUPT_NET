# Renders every icon frame from app.ico into a contact sheet for visual QA.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File tools\icon-preview.ps1

param(
    [string]$Ico = (Join-Path $PSScriptRoot '..\Resources\app.ico'),
    [string]$OutPng = (Join-Path $PSScriptRoot '..\..\.tools\icon-check\sheet.png')
)

Add-Type -AssemblyName System.Drawing
$ErrorActionPreference = 'Stop'

$sizes = @(16, 24, 32, 48, 64, 128, 256)
$zoom = 3
$pad = 12
$label = 18
$cell = 256 * $zoom
$cols = 3
$rows = [int][Math]::Ceiling($sizes.Count / $cols)
$w = $cols * ($cell + $pad) + $pad
$h = $rows * ($cell + $pad + $label) + $pad

$sheet = [System.Drawing.Bitmap]::new($w, $h, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$gs = [System.Drawing.Graphics]::FromImage($sheet)
$gs.Clear([System.Drawing.Color]::FromArgb(255, 245, 246, 248))
$gs.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::NearestNeighbor
$gs.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::Half
$font = [System.Drawing.Font]::new('Segoe UI', 10)
$textBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 60, 64, 72))

$icon = [System.Drawing.Icon]::new($Ico)
for ($i = 0; $i -lt $sizes.Count; $i++) {
    $size = $sizes[$i]
    $col = $i % $cols
    $row = [int][Math]::Floor($i / $cols)
    $x = $pad + $col * ($cell + $pad)
    $y = $pad + $row * ($cell + $pad + $label)

    $frame = [System.Drawing.Icon]::new($icon, $size, $size).ToBitmap()
    $gs.DrawString("$size px", $font, $textBrush, [single]$x, [single]($y))
    $gs.DrawImage($frame, [System.Drawing.Rectangle]::new($x, $y + $label, $cell, $cell))
    $frame.Dispose()
}
$icon.Dispose()
$gs.Dispose()
$font.Dispose()
$textBrush.Dispose()

$dir = Split-Path -Parent $OutPng
if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
$sheet.Save($OutPng, [System.Drawing.Imaging.ImageFormat]::Png)
$sheet.Dispose()
Write-Output "sheet: $OutPng"
