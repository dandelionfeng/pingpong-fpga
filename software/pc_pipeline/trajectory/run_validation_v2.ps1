[CmdletBinding()]
param(
    [string]$OutputDirectory,
    [string]$Python,
    [string]$OpenCVDir,
    [string]$BuildDirectory,
    [string]$VisualStudioPath
)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) -Parent
if(-not $OutputDirectory){$OutputDirectory=Join-Path $taskRoot '_deliveries\part3_v2_validation'}
if(-not $Python){$Python=Join-Path $taskRoot '.venv\Scripts\python.exe'}
if(-not $BuildDirectory){$BuildDirectory=Join-Path $PSScriptRoot 'build-ninja-release'}
if(-not(Test-Path -LiteralPath $Python)){throw 'Python missing; pass -Python with numpy/opencv-python/matplotlib.'}
$taskDependency=Join-Path (Split-Path $PSScriptRoot -Parent) 'ball_measurement'
if(-not(Test-Path -LiteralPath (Join-Path $taskDependency 'CMakeLists.txt'))){
    throw "Second-part dependency missing: expected $taskDependency (merge/fix the B second-part path before running v2)."
}
$taskBuild=Join-Path $OutputDirectory 'build-console.txt'
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$taskBuilder=Join-Path $PSScriptRoot 'build_and_test.bat'
if(-not(Test-Path -LiteralPath $taskBuilder)){throw "Build entry missing: $taskBuilder"}
$taskBuildArgs=@('-BuildDirectory',$BuildDirectory)
if($OpenCVDir){$taskBuildArgs+=@('-OpenCVDir',$OpenCVDir)}
if($VisualStudioPath){$taskBuildArgs+=@('-VisualStudioPath',$VisualStudioPath)}
& $taskBuilder @taskBuildArgs > $taskBuild 2>&1
if($LASTEXITCODE -ne 0){throw "C++ build/test failed; see $taskBuild"}
function Invoke-TaskStep([string]$Program,[string[]]$Arguments,[string]$Log){
    & $Program @Arguments 2>&1 | Tee-Object -FilePath $Log
    if($LASTEXITCODE -ne 0){throw "Step failed: $Program $Arguments"}
}
$taskFixtures=Join-Path $taskRoot 'tools\fixtures'
Invoke-TaskStep $Python @((Join-Path $taskFixtures 'trajectory_v2_fixture.py'),'--output',$OutputDirectory) (Join-Path $OutputDirectory 'fixture-run.txt')
$taskInputs=Join-Path $OutputDirectory 'inputs';$taskResults=Join-Path $OutputDirectory 'results'
New-Item -ItemType Directory -Path $taskResults -Force | Out-Null
$taskCli=Join-Path $BuildDirectory 'trajectory_cli.exe'
if(-not(Test-Path -LiteralPath $taskCli)){throw "Built CLI missing: $taskCli"}
foreach($taskMode in @('board','board_broad')){
    Invoke-TaskStep $taskCli @('calibrate',(Join-Path $taskInputs ($taskMode+'_manifest.json')),(Join-Path $taskResults ($taskMode+'_calibration.json'))) (Join-Path $OutputDirectory ($taskMode+'-run.txt'))
    $taskHeldout=$taskMode+'_heldout.json'
    Invoke-TaskStep $Python @((Join-Path $taskFixtures 'trajectory_calibration_score.py'),'--inputs',$taskInputs,'--calibration',(Join-Path $taskResults ($taskMode+'_calibration.json')),'--heldout',$taskHeldout,'--report',(Join-Path $OutputDirectory ($taskMode+'-score.json'))) (Join-Path $OutputDirectory ($taskMode+'-score-run.txt'))
}
Copy-Item -LiteralPath (Join-Path $taskResults 'board_broad_calibration.json') -Destination (Join-Path $taskInputs 'estimated_calibration.json')
Invoke-TaskStep $taskCli @((Join-Path $taskInputs 'manifest_v2.json'),$taskResults) (Join-Path $OutputDirectory 'run.txt')
Invoke-TaskStep $Python @((Join-Path $taskFixtures 'trajectory_v2_score.py'),'--root',$OutputDirectory) (Join-Path $OutputDirectory 'score-run.txt')
Invoke-TaskStep $taskCli @('rectify-preview',(Join-Path $taskResults 'board_broad_calibration.json'),(Join-Path $taskInputs 'boards_broad\board_30_0.png'),(Join-Path $taskInputs 'boards_broad\board_30_1.png'),(Join-Path $OutputDirectory 'rectification-preview.png')) (Join-Path $OutputDirectory 'preview-run.txt')
Invoke-TaskStep $Python @((Join-Path $taskFixtures 'trajectory_event_evidence.py'),'--root',$OutputDirectory) (Join-Path $OutputDirectory 'evidence-run.txt')
$taskPreviousPlotCache=$env:MPLCONFIGDIR
try {
    $env:MPLCONFIGDIR=Join-Path $OutputDirectory 'plot-cache'
    Invoke-TaskStep $Python @((Join-Path $taskFixtures 'trajectory_v2_gallery.py'),'--root',$OutputDirectory) (Join-Path $OutputDirectory 'gallery-run.txt')
} finally { $env:MPLCONFIGDIR=$taskPreviousPlotCache }
Write-Output 'PART3_V2_VALIDATION_PASS'
