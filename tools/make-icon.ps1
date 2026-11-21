# Writes Resources/app.ico (16..256) and the 256px preview PNG.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File tools\make-icon.ps1

param(
    [string]$OutFile = (Join-Path $PSScriptRoot '..\Resources\app.ico'),
    [string]$PreviewPng = (Join-Path $PSScriptRoot '..\Resources\app-icon-256.png')
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'icon-lib.ps1')

$sizes = @(16, 24, 32, 48, 64, 128, 256)
$frames = @()
$preview = $null

foreach ($size in $sizes) {
    $bmp = New-IconBitmap $size
    if ($size -eq 256) {
        $preview = $bmp
    }

    # Only the 256 frame is stored as PNG; everything else uses a 32bpp DIB so
    # older shell surfaces can read it.
    if ($size -ge 256) {
        $ms = [System.IO.MemoryStream]::new()
        $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
        $frames += ,@{ Size = $size; Bytes = $ms.ToArray() }
        $ms.Dispose()
    }
    else {
        $frames += ,@{ Size = $size; Bytes = (Get-DibBytes $bmp) }
    }

    if ($size -ne 256) {
        $bmp.Dispose()
    }
}

$outDir = Split-Path -Parent $OutFile
if (-not (Test-Path -LiteralPath $outDir)) {
    New-Item -ItemType Directory -Path $outDir | Out-Null
}

$fs = [System.IO.File]::Create($OutFile)
$bw = [System.IO.BinaryWriter]::new($fs)
try {
    $bw.Write([int16]0)
    $bw.Write([int16]1)
    $bw.Write([int16]$frames.Count)
    $offset = 6 + 16 * $frames.Count
    foreach ($f in $frames) {
        $dim = if ($f.Size -ge 256) { 0 } else { $f.Size }
        $bw.Write([byte]$dim)
        $bw.Write([byte]$dim)
        $bw.Write([byte]0)
        $bw.Write([byte]0)
        $bw.Write([int16]1)
        $bw.Write([int16]32)
        $bw.Write([int]$f.Bytes.Length)
        $bw.Write([int]$offset)
        $offset += $f.Bytes.Length
    }
    foreach ($f in $frames) {
        $bw.Write([byte[]]$f.Bytes)
    }
}
finally {
    $bw.Dispose()
    $fs.Dispose()
}

if ($preview) {
    $preview.Save($PreviewPng, [System.Drawing.Imaging.ImageFormat]::Png)
    $preview.Dispose()
}

Write-Output "icon: $OutFile"
Write-Output "preview: $PreviewPng"
