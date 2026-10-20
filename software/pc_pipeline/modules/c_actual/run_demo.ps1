# C_ACTUAL_INTERFACE_V2_4 one-command demo.
#
#   powershell -ExecutionPolicy Bypass -File run_demo.ps1
#   powershell -ExecutionPolicy Bypass -File run_demo.ps1 -Unified
#
# Runs an image demo and (when a sample video exists) a video demo, writing
# results into out\. Missing models report MISSING_MODEL instead of a stack trace.
#
# DEFAULT = split hand + racket (the V2.3 detectors). The unified 3-class model is
# shipped and supported, but it measured LOWER hand recall on the real target
# domain (BNDSTT: R 0.4444 vs 0.6481 at conf 0.25), so it is opt-in:
#
#   -Unified   one 960 model serves hand + racket in a single inference pass
#              (~21% faster per frame on CPU, one model to quantize for the NPU)
#
# See C_PERCEPTION_CAPTAIN_INTEGRATION_V2_4_REPORT.md for the measured tables.
#
# PATH NOTE: this script always passes RELATIVE paths and runs from the package
# root. Windows PowerShell 5.1 mangles non-ASCII characters when handing
# arguments to a native .exe, so keep the package in an ASCII path (e.g.,
# D:\c_iface). If you must use a non-ASCII path, run this from PowerShell 7+.

param(
    [switch]$Unified
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$cli     = '.\bin\c_perception_cli.exe'
$ball    = '.\models\balltrack_tracknetv3.onnx'
$unifiedModel = '.\models\pingpong_yolov8n_gray_3cls_960.onnx'
$hand    = '.\models\hand_yolov8n_gray_final_v3_960.onnx'
$racket  = '.\models\racket_yolov8n_gray.onnx'
$config  = '.\config\inference.yaml'

$useUnified = $Unified -and (Test-Path $unifiedModel)
if ($Unified -and -not (Test-Path $unifiedModel)) {
    Write-Host "WARNING: -Unified requested but $unifiedModel is missing; using split models." -ForegroundColor Yellow
}
$modelArgs = @('--ball-model', $ball)
if ($useUnified) {
    $modelArgs += @('--unified-model', $unifiedModel)
} else {
    $modelArgs += @('--hand-model', $hand, '--racket-model', $racket)
}

Write-Host "C perception - CAPTAIN INTEGRATION V2.4"
Write-Host "  root: $root"
if ($useUnified) {
    Write-Host "  mode: unified 3-class (ONE YOLO pass for hand + racket, opt-in)"
} else {
    Write-Host "  mode: split hand + racket (default, V2.3 detectors)"
}
Write-Host ""

# ---------------------------------------------------------------- preflight
$missing = @()
$required = @($cli, $ball)
if ($useUnified) { $required += $unifiedModel } else { $required += @($hand, $racket) }
foreach ($p in $required) {
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
foreach ($p in $required) {
    if ($p -eq $cli) { continue }
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
$selfArgs = @('--self-test', '--image', $sampleImage) + $modelArgs
if (Test-Path $config) { $selfArgs += @('--config', $config) }
& $cli @selfArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "SELF_TEST_FAILED (exit $LASTEXITCODE)" -ForegroundColor Red
    exit 3
}
Write-Host ""

# ---------------------------------------------------------------- image demo
Write-Host "--- image demo ---"
$imgArgs = @('--image', $sampleImage) + $modelArgs +
           @('--output', '.\out\result_image.jsonl', '--overlay', '.\out\overlay_image.png')
if (Test-Path $config) { $imgArgs += @('--config', $config) }
& $cli @imgArgs
Write-Host ""

# ---------------------------------------------------------------- video demo
$sampleVideo = Get-ChildItem -Path '.\examples' -Filter '*.mp4' -ErrorAction SilentlyContinue |
               Select-Object -First 1
if ($sampleVideo) {
    Write-Host "--- video demo: $($sampleVideo.Name) ---"
    $vidArgs = @('--video', ('.\examples\' + $sampleVideo.Name)) + $modelArgs +
               @('--output', '.\out\result_video.jsonl', '--overlay', '.\out\overlay_video.mp4')
    if (Test-Path $config) { $vidArgs += @('--config', $config) }
    & $cli @vidArgs
} else {
    Write-Host "--- video demo skipped (no .mp4 in examples\) ---"
}

Write-Host ""
Write-Host "Demo finished. Results are in: out" -ForegroundColor Green
Get-ChildItem '.\out' | ForEach-Object { Write-Host ("  " + $_.Name) }
