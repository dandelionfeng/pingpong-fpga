param(
    [string]$TdRoot = 'C:\Anlogic\TD_Release_2026.1_SP2.200.067'
)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskExe = Join-Path $TdRoot 'bin\td_commands_prompt.exe'
if (-not (Test-Path -LiteralPath $taskExe -PathType Leaf)) { throw "TD executable not found: $taskExe" }
$taskRun = Join-Path $taskRoot ('tmp\td-smoke-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory -Path $taskRun | Out-Null
foreach ($taskFile in @('run.tcl','smoke_top.v','smoke.sdc')) {
    Copy-Item -LiteralPath (Join-Path $taskRoot "fpga\smoke\td_batch\$taskFile") -Destination $taskRun
}
Push-Location -LiteralPath $taskRun
try {
    Write-Host "Running TD smoke build. Output: $taskRun"
    # Relative Tcl name avoids TD launcher parsing failures with spaces in paths.
    & $taskExe run.tcl *> console.log
    $taskExit = $LASTEXITCODE
    $taskLog = Get-Content -LiteralPath console.log -Raw
    if ($taskExit -ne 0 -or -not (Test-Path SUCCESS.txt) -or (Test-Path FAILURE.txt) -or $taskLog -notmatch 'TD_SMOKE_PASS') {
        throw "TD failed or completion was not verified (exit $taskExit). See $taskRun\console.log"
    }
    foreach ($taskOutput in @('gate.db','gate.area','route.db','route.area','route_timing.rpt')) {
        if (-not (Test-Path -LiteralPath $taskOutput) -or (Get-Item -LiteralPath $taskOutput).Length -eq 0) {
            throw "Missing or empty output: $taskOutput"
        }
    }
    $taskHasher = [System.Security.Cryptography.SHA256]::Create()
    $taskStream = [System.IO.File]::OpenRead((Join-Path $taskRun 'route.db'))
    try {
        $taskDigest = [BitConverter]::ToString($taskHasher.ComputeHash($taskStream)).Replace('-', '')
        Set-Content -LiteralPath route-sha256.txt -Value "$taskDigest  route.db"
    } finally { $taskStream.Dispose(); $taskHasher.Dispose() }
    Write-Host 'PASS: synthesis, place, route and timing report generation completed.'
    Write-Host 'Toolchain test only: no verified board pinout. Bitstream generation is intentionally excluded.'
    Write-Host "Logs and outputs: $taskRun"
} finally { Pop-Location }
