param([string]$Root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path)
$ErrorActionPreference = 'Stop'
$taskTools = Join-Path $Root '.tools'
$taskPython = Join-Path $Root '.venv/a_pipeline/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { python -m venv (Join-Path $Root '.venv/a_pipeline'); if ($LASTEXITCODE) { throw 'venv failed' } }
& $taskPython -m pip install --disable-pip-version-check 'aqtinstall==3.3.0' 'numpy==2.5.3' 'psutil==7.2.2' 'pillow==12.3.0' 'clang-format==23.1.2'
if ($LASTEXITCODE) { throw 'Python dependencies failed' }
$taskDownload = Join-Path $taskTools 'downloads/opencv-4.13.0-windows.exe'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $taskDownload) | Out-Null
if (-not (Test-Path -LiteralPath $taskDownload)) {
    Invoke-WebRequest 'https://github.com/opencv/opencv/releases/download/4.13.0/opencv-4.13.0-windows.exe' -OutFile $taskDownload
}
if((Get-FileHash -LiteralPath $taskDownload -Algorithm SHA256).Hash -ne 'F0E98C302464D6860777A7015065E11B9B271B5394E6BA92663F0CF1FC303F2C'){throw 'OpenCV archive SHA-256 mismatch'}
$taskCv = Join-Path $taskTools 'opencv413'
if (-not (Test-Path -LiteralPath (Join-Path $taskCv 'opencv/build/OpenCVConfig.cmake'))) {
    New-Item -ItemType Directory -Force -Path $taskCv | Out-Null
    $taskExtract = Start-Process -FilePath $taskDownload -ArgumentList @('-y', ('-o"{0}"' -f $taskCv)) -WindowStyle Hidden -PassThru -Wait
    if ($taskExtract.ExitCode) { throw 'OpenCV extraction failed' }
}
if (-not (Test-Path -LiteralPath (Join-Path $taskTools 'qt/6.8.3/msvc2022_64/lib/cmake/Qt6/Qt6Config.cmake'))) {
    & $taskPython -m aqt install-qt windows desktop 6.8.3 win64_msvc2022_64 -O (Join-Path $taskTools 'qt') --archives qtbase qttools
    if ($LASTEXITCODE) { throw 'Qt installation failed' }
}
Get-FileHash -LiteralPath $taskDownload -Algorithm SHA256
