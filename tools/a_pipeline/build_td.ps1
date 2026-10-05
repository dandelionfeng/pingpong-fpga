param([string]$TdRoot='C:/Anlogic/TD_Release_2026.1_SP2.200.067')
$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$taskExe=Join-Path $TdRoot 'bin/td_commands_prompt.exe'
if(-not (Test-Path -LiteralPath $taskExe)){throw "TD missing: $taskExe"}
$taskRun=Join-Path $taskRoot ('build/a-motion-td-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+[guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory -Path (Join-Path $taskRun 'src') | Out-Null
$taskInputs=@(Get-ChildItem -LiteralPath (Join-Path $taskRoot 'fpga/rtl/a_motion') -Filter '*.v')+@(Get-Item -LiteralPath (Join-Path $taskRoot 'fpga/projects/a_motion_td/a_motion_compile_top.v'))
$taskHashes=@{}
foreach($taskFile in $taskInputs){
  Copy-Item -LiteralPath $taskFile.FullName -Destination (Join-Path $taskRun 'src')
  $taskHashes[$taskFile.Name]=(Get-FileHash -LiteralPath $taskFile.FullName -Algorithm SHA256).Hash
}
foreach($taskName in @('create_and_synth.tcl','core.sdc')){
  $taskFile=Join-Path $taskRoot ('fpga/projects/a_motion_td/'+$taskName)
  Copy-Item -LiteralPath $taskFile -Destination $taskRun
  $taskHashes[$taskName]=(Get-FileHash -LiteralPath $taskFile -Algorithm SHA256).Hash
}
$taskHashes | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskRun 'source-sha256.json') -Encoding utf8
Push-Location -LiteralPath $taskRun
try{
  $ErrorActionPreference='Continue'
  try{& $taskExe create_and_synth.tcl *> console.log;$taskExit=$LASTEXITCODE}
  finally{$ErrorActionPreference='Stop'}
  $taskLog=Get-Content -LiteralPath console.log -Raw
  if($taskExit -ne 0 -or -not (Test-Path SUCCESS.txt) -or (Test-Path FAILURE.txt) -or $taskLog -notmatch 'A_MOTION_SYNTH_PASS'){throw "TD synthesis failed: $taskRun/console.log"}
  foreach($taskName in @('a_motion.al','core_gate.area','core_gate.db')){
    if(-not (Test-Path -LiteralPath $taskName) -or (Get-Item -LiteralPath $taskName).Length -eq 0){throw "TD output missing: $taskName"}
  }
  Set-Content -LiteralPath (Join-Path $taskRoot 'build/a-motion-td-latest.txt') -Value $taskRun -Encoding utf8
  Write-Host "PASS: PH1A90SEG324 core synthesis; project $taskRun/a_motion.al"
  Write-Host 'Board pin assignment, place/route, timing closure, DDR/IP and bitstream require the board SDK.'
}finally{Pop-Location}
