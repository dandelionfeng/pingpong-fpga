[CmdletBinding()]
param([string]$OutputDirectory, [string]$Python, [string]$OpenCVDir)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) -Parent
if(-not $OutputDirectory){$OutputDirectory=Join-Path $taskRoot '_deliveries\part3_v1_validation'}
if(-not $Python){$Python=Join-Path $taskRoot '.venv\Scripts\python.exe'}
if(-not(Test-Path -LiteralPath $Python)){throw 'Python missing. Pass -Python <python.exe> with numpy and opencv-python.'}
if($OpenCVDir){ & (Join-Path $PSScriptRoot 'build_and_test.bat') -OpenCVDir $OpenCVDir }else{ & (Join-Path $PSScriptRoot 'build_and_test.bat') }
if($LASTEXITCODE -ne 0){throw 'C++ build/test failed'}
& $Python (Join-Path $taskRoot 'tools\fixtures\trajectory_fixture.py') --output $OutputDirectory
if($LASTEXITCODE -ne 0){throw 'Fixture generation failed'}
$taskCli=Join-Path $PSScriptRoot 'build-ninja-release\trajectory_cli.exe'
& $taskCli (Join-Path $OutputDirectory 'inputs\manifest.json') (Join-Path $OutputDirectory 'results') 2>&1 | Tee-Object -FilePath (Join-Path $OutputDirectory 'run.txt')
if($LASTEXITCODE -ne 0){throw 'Trajectory execution failed'}
& $Python (Join-Path $taskRoot 'tools\fixtures\trajectory_score.py') --truth (Join-Path $OutputDirectory 'truth\expected.json') --results (Join-Path $OutputDirectory 'results') --report (Join-Path $OutputDirectory 'score.json')
if($LASTEXITCODE -ne 0){throw 'Trajectory scoring failed'}
& $taskCli calibrate (Join-Path $OutputDirectory 'inputs\board_manifest.json') (Join-Path $OutputDirectory 'results\board_calibration.json') 2>&1 | Tee-Object -FilePath (Join-Path $OutputDirectory 'calibration-run.txt')
if($LASTEXITCODE -ne 0){throw 'Chessboard calibration failed'}
& $Python (Join-Path $taskRoot 'tools\fixtures\trajectory_calibration_score.py') --inputs (Join-Path $OutputDirectory 'inputs') --calibration (Join-Path $OutputDirectory 'results\board_calibration.json') --report (Join-Path $OutputDirectory 'calibration-score.json')
if($LASTEXITCODE -ne 0){throw 'Heldout board scoring failed'}
Write-Output 'PART3_VALIDATION_PASS'
