# Shared icon drawing helpers. Keep this file ASCII-only: Windows PowerShell 5.1
# reads BOM-less files as ANSI, and a multi-byte comment can swallow code lines.

Add-Type -AssemblyName System.Drawing

function New-SquirclePath([single]$x, [single]$y, [single]$w, [single]$h, [single]$exp) {
    $pts = [System.Collections.Generic.List[System.Drawing.PointF]]::new()
    $cx = $x + $w / 2
    $cy = $y + $h / 2
    $rx = $w / 2
    $ry = $h / 2
    $n = 240
    for ($i = 0; $i -lt $n; $i++) {
        $t = 2 * [Math]::PI * $i / $n
        $ct = [Math]::Cos($t)
        $st = [Math]::Sin($t)
        $px = $cx + $rx * [Math]::Sign($ct) * [Math]::Pow([Math]::Abs($ct), 2 / $exp)
        $py = $cy + $ry * [Math]::Sign($st) * [Math]::Pow([Math]::Abs($st), 2 / $exp)
        $pts.Add([System.Drawing.PointF]::new([single]$px, [single]$py))
    }
    $path = [System.Drawing.Drawing2D.GraphicsPath]::new()
    $path.AddPolygon($pts.ToArray())
    return $path
}

function New-RingPen([System.Drawing.Color]$color, [single]$width) {
    $pen = [System.Drawing.Pen]::new($color, $width)
    $pen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $pen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $pen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
    return $pen
}

function New-IconBitmap([int]$size) {
    $ss = 4
    $big = [System.Drawing.Bitmap]::new($size * $ss, $size * $ss, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($big)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $g.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
    $g.Clear([System.Drawing.Color]::Transparent)

    $s = [single]($size * $ss)
    $bgPath = New-SquirclePath 0 0 $s $s ([single]5.0)
    $bg = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 0x2F, 0x6B, 0xFF))
    $g.FillPath($bg, $bgPath)
    $bg.Dispose()

    $white = [System.Drawing.Color]::White
    $tint = [System.Drawing.Color]::FromArgb(255, 0xBF, 0xD3, 0xFF)

    $cx = [single]($s * 0.5)
    $cy = [single]($s * 0.5)

    if ($size -le 32) {
        # Tiny frames: filled annuli survive downscaling far better than hairlines.
        if ($size -le 16) { $ro = 0.255; $ri = 0.125; $dxK = 0.100; $dyK = 0.055 }
        elseif ($size -le 24) { $ro = 0.245; $ri = 0.120; $dxK = 0.105; $dyK = 0.058 }
        else { $ro = 0.235; $ri = 0.115; $dxK = 0.108; $dyK = 0.059 }

        $rOuter = [single]($s * $ro)
        $rInner = [single]($s * $ri)
        $dx = [single]($s * $dxK)
        $dy = [single]($s * $dyK)

        foreach ($spec in @(
            @{ Sign = -1; Color = $white },
            @{ Sign = 1; Color = $tint }
        )) {
            $rx = [single]($cx + $spec.Sign * $dx)
            $ry = [single]($cy + $spec.Sign * $dy)
            $ring = [System.Drawing.Drawing2D.GraphicsPath]::new()
            $ring.FillMode = [System.Drawing.Drawing2D.FillMode]::Alternate
            $ring.AddEllipse($rx - $rOuter, $ry - $rOuter, $rOuter * 2, $rOuter * 2)
            $ring.AddEllipse($rx - $rInner, $ry - $rInner, $rInner * 2, $rInner * 2)
            $brush = [System.Drawing.SolidBrush]::new($spec.Color)
            $g.FillPath($brush, $ring)
            $brush.Dispose()
            $ring.Dispose()
        }
    }
    else {
        $strokeK = 0.078
        $rK = 0.150
        $offK = 0.050
        $stroke = [single]($s * $strokeK)
        $r = [single]($s * $rK)
        $off = [single]($s * $offK)
        $d = $r * 2

        $penWhite = New-RingPen $white $stroke
        $g.DrawArc($penWhite, [System.Drawing.RectangleF]::new($cx - $off - $r, $cy - $r, $d, $d), 120, 240)
        $penWhite.Dispose()

        $penTint = New-RingPen $tint $stroke
        $g.DrawArc($penTint, [System.Drawing.RectangleF]::new($cx + $off - $r, $cy - $r, $d, $d), 300, 240)
        $penTint.Dispose()
    }

    $g.Dispose()
    $bgPath.Dispose()

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

function Get-DibBytes([System.Drawing.Bitmap]$bmp) {
    $size = $bmp.Width
    $maskStride = [int]([Math]::Ceiling($size / 32.0) * 4)
    $xorSize = $size * $size * 4
    $maskSize = $maskStride * $size

    $ms = [System.IO.MemoryStream]::new()
    $w = [System.IO.BinaryWriter]::new($ms)
    $w.Write([int]40)
    $w.Write([int]$size)
    $w.Write([int]($size * 2))
    $w.Write([int16]1)
    $w.Write([int16]32)
    $w.Write([int]0)
    $w.Write([int]($xorSize + $maskSize))
    $w.Write([int]0)
    $w.Write([int]0)
    $w.Write([int]0)
    $w.Write([int]0)

    $rect = [System.Drawing.Rectangle]::new(0, 0, $size, $size)
    $data = $bmp.LockBits($rect, [System.Drawing.Imaging.ImageLockMode]::ReadOnly, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    try {
        $row = [byte[]]::new($size * 4)
        for ($y = $size - 1; $y -ge 0; $y--) {
            [System.Runtime.InteropServices.Marshal]::Copy(
                [IntPtr]::Add($data.Scan0, $y * $data.Stride), $row, 0, $row.Length)
            $w.Write($row)
        }
    }
    finally {
        $bmp.UnlockBits($data)
    }

    $zero = [byte[]]::new($maskStride)
    for ($y = 0; $y -lt $size; $y++) {
        $w.Write($zero)
    }

    $w.Flush()
    $bytes = $ms.ToArray()
    $w.Dispose()
    $ms.Dispose()
    return $bytes
}
