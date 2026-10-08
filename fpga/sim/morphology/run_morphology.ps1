$ErrorActionPreference='Stop'
$root=Split-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) -Parent
$env:PATH="$(Join-Path $root '.tools\iverilog\bin');$env:PATH"
$work=Join-Path $PSScriptRoot 'build';New-Item -ItemType Directory -Path $work -Force|Out-Null;Push-Location $work
try {
 & iverilog -g2012 -s tb_morphology_mask_chain -o morphology.vvp (Join-Path $PSScriptRoot '..\..\rtl\morphology\morphology_mask_chain.sv') (Join-Path $PSScriptRoot 'tb_morphology_mask_chain.sv') 2>&1|Tee-Object compile.log
 if($LASTEXITCODE-ne 0){exit $LASTEXITCODE};& vvp morphology.vvp 2>&1|Tee-Object run.log;exit $LASTEXITCODE
}finally{Pop-Location}
