param(
    [string]$TdRoot = 'C:\Anlogic\TD_Release_2026.1_SP2.200.067'
)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskExe = Join-Path $TdRoot 'bin\td_commands_prompt.exe'
if (-not (Test-Path -LiteralPath $taskExe -PathType Leaf)) { throw "TD executable not found: $taskExe" }
$taskRun = Join-Path $taskRoot ('build\afh03-image-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory -Path (Join-Path $taskRun 'src') | Out-Null
$taskInputs = @(Get-ChildItem -LiteralPath (Join-Path $taskRoot 'fpga\rtl\afh03_image') -Filter '*.v') + @(Get-Item -LiteralPath (Join-Path $taskRoot 'fpga\afh03_image\td\afh03_image_compile_top.v'))
foreach ($taskFile in $taskInputs) { Copy-Item -LiteralPath $taskFile.FullName -Destination (Join-Path $taskRun 'src') }
foreach ($taskFile in @('create_and_synth.tcl','core.sdc')) {
    Copy-Item -LiteralPath (Join-Path $taskRoot "fpga\afh03_image\td\$taskFile") -Destination $taskRun
}
$taskHashes = @{}
foreach ($taskFile in $taskInputs) { $taskHashes[$taskFile.Name] = (Get-FileHash -LiteralPath $taskFile.FullName -Algorithm SHA256).Hash }
$taskHashes | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskRun 'source-sha256.json') -Encoding UTF8
Push-Location -LiteralPath $taskRun
try {
    Write-Host "Creating and synthesizing TD project: $taskRun"
    # TD launcher's argument parser requires a relative Tcl filename here.
    # Windows PowerShell treats native stderr as an ErrorRecord. Preserve the
    # complete log, then decide success from exit code AND TD output markers.
    $ErrorActionPreference = 'Continue'
    try { & $taskExe create_and_synth.tcl *> console.log; $taskExit = $LASTEXITCODE }
    finally { $ErrorActionPreference = 'Stop' }
    $taskLog = Get-Content -LiteralPath console.log -Raw
    if ($taskExit -ne 0 -or -not (Test-Path SUCCESS.txt) -or (Test-Path FAILURE.txt) -or $taskLog -notmatch 'AFH03_IMAGE_SYNTH_PASS') {
        throw "TD synthesis not verified (exit $taskExit). See $taskRun\console.log"
    }
    foreach ($taskOutput in @('afh03_image.al','core_gate.area','core_gate.db')) {
        if (-not (Test-Path -LiteralPath $taskOutput) -or (Get-Item -LiteralPath $taskOutput).Length -eq 0) { throw "Missing or empty output: $taskOutput" }
    }
    $taskBuildRoot = Split-Path -Parent $taskRun
    Set-Content -LiteralPath (Join-Path $taskBuildRoot 'afh03-image-latest.txt') -Value $taskRun -Encoding UTF8
    Write-Host 'PASS: native TD project and core synthesis. No board pin mapping, place/route or bitstream.'
    Write-Host "Open in TD: $taskRun\afh03_image.al"
} finally { Pop-Location }
