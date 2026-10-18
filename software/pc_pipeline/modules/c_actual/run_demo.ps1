# C_ACTUAL_INTERFACE_V2_1 one-command demo.
#
#   powershell -ExecutionPolicy Bypass -File run_demo.ps1
#
# Runs an image demo and (when a sample video exists) a video demo, writing
# results into out\. Missing models report MISSING_MODEL instead of a stack trace.
#
# PATH NOTE: this script always passes RELATIVE paths and runs from the package
# root. Windows PowerShell 5.1 mangles non-ASCII characters when handing
# arguments to a native .exe, so keep the package in an ASCII path (e.g.
# D:\c_iface). If you must use a non-ASCII path, run this from PowerShell 7+.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$cli     = '.\bin\c_perception_cli.exe'
$ball    = '.\models\balltrack_tracknetv3.onnx'
$hand    = '.\models\hand_yolov8n_gray_final_v3_960.onnx'
$racket  = '.\models\racket_yolov8n_gray.onnx'
$config  = '.\config\inference.yaml'

Write-Host "C perception - CAPTAIN INTEGRATION V2.3"
Write-Host "  root: $root"
Write-Host ""

# ---------------------------------------------------------------- preflight
$missing = @()
foreach ($p in @($cli, $ball, $hand, $racket)) {
    if (-not (Test-Path $p)) { $missing += $p }
}
if ($missing.Count -gt 0) {
    Write-Host "MISSING_MODEL: the following files were not found:" -ForegroundColor Red
    foreach ($m in $missing) { Write-Host "  - $m" -ForegroundColor Red }
    Write-Host ""
    Write-Host "Expected layout: bin\c_perception_cli.exe, models\*.onnx"
    Write-Host "See MODEL_SHA256.txt for the model hashes."
    exit 2
}

Write-Host "models found:" -ForegroundColor Green
foreach ($p in @($ball, $hand, $racket)) {
    $f = Get-Item $p
    Write-Host ("  {0,-44} {1,12:N0} bytes" -f $f.Name, $f.Length)
}
Write-Host ""

New-Item -ItemType Directory -Force -Path '.\out' | Out-Null

$sampleImage = '.\examples\sample_frame.png'
if (-not (Test-Path $sampleImage)) {
    $sampleImage = '.\out\blank.png'
    Add-Type -AssemblyName System.Drawing
    $bmp = New-Object System.Drawing.Bitmap 1280, 720
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.Clear([System.Drawing.Color]::FromArgb(90, 90, 90))
    $g.Dispose()
    $bmp.Save((Join-Path $root 'out\blank.png'), [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
}

# ---------------------------------------------------------------- self test
Write-Host "--- model self-test ---"
$selfArgs = @('--self-test', '--image', $sampleImage,
              '--ball-model', $ball, '--hand-model', $hand, '--racket-model', $racket)
if (Test-Path $config) { $selfArgs += @('--config', $config) }
& $cli @selfArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "SELF_TEST_FAILED (exit $LASTEXITCODE)" -ForegroundColor Red
    exit 3
}
Write-Host ""

# ---------------------------------------------------------------- image demo
Write-Host "--- image demo ---"
$imgArgs = @('--image', $sampleImage,
             '--ball-model', $ball, '--hand-model', $hand, '--racket-model', $racket,
             '--output', '.\out\result_image.jsonl',
             '--overlay', '.\out\overlay_image.png')
if (Test-Path $config) { $imgArgs += @('--config', $config) }
& $cli @imgArgs
Write-Host ""

# ---------------------------------------------------------------- video demo
$sampleVideo = Get-ChildItem -Path '.\examples' -Filter '*.mp4' -ErrorAction SilentlyContinue |
               Select-Object -First 1
if ($sampleVideo) {
    Write-Host "--- video demo: $($sampleVideo.Name) ---"
    $vidArgs = @('--video', ('.\examples\' + $sampleVideo.Name),
                 '--ball-model', $ball, '--hand-model', $hand, '--racket-model', $racket,
                 '--output', '.\out\result_video.jsonl',
                 '--overlay', '.\out\overlay_video.mp4')
    if (Test-Path $config) { $vidArgs += @('--config', $config) }
    & $cli @vidArgs
} else {
    Write-Host "--- video demo skipped (no .mp4 in examples\) ---"
}

Write-Host ""
Write-Host "Demo finished. Results are in: out" -ForegroundColor Green
Get-ChildItem '.\out' | ForEach-Object { Write-Host ("  " + $_.Name) }
