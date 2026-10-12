param([string]$Name='A-USB-Stereo-Pipeline-1.0.1-Windows')
$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$taskBuild=Join-Path $taskRoot 'build/a_pipeline_windows'
$taskPackage=Join-Path $taskRoot ('dist/'+$Name)
if(Test-Path -LiteralPath $taskPackage){throw 'Choose a fresh package name; existing packages are preserved'}
New-Item -ItemType Directory -Path $taskPackage | Out-Null
foreach($taskName in @('pipeline_cli.exe','pipeline_gui.exe')){
  Copy-Item -LiteralPath (Join-Path $taskBuild $taskName) -Destination $taskPackage
}
Get-ChildItem -LiteralPath $taskBuild -Filter '*.dll' | ForEach-Object {Copy-Item -LiteralPath $_.FullName -Destination $taskPackage}
foreach($taskName in @('platforms','styles','imageformats','generic','networkinformation','tls')){
  $taskPath=Join-Path $taskBuild $taskName
  if(Test-Path -LiteralPath $taskPath){Copy-Item -LiteralPath $taskPath -Destination $taskPackage -Recurse}
}
$taskCrt='C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Redist/MSVC/14.44.35112/x64/Microsoft.VC143.CRT'
Get-ChildItem -LiteralPath $taskCrt -Filter '*.dll' | ForEach-Object {Copy-Item -LiteralPath $_.FullName -Destination $taskPackage}
$taskOpenMp='C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Redist/MSVC/14.44.35112/x64/Microsoft.VC143.OpenMP/vcomp140.dll'
if(Test-Path -LiteralPath $taskOpenMp){Copy-Item -LiteralPath $taskOpenMp -Destination $taskPackage}
Copy-Item -LiteralPath (Join-Path $taskRoot 'software/pc_pipeline/configs') -Destination $taskPackage -Recurse
Copy-Item -LiteralPath (Join-Path $taskRoot 'software/pc_pipeline/contracts') -Destination $taskPackage -Recurse
Copy-Item -LiteralPath (Join-Path $taskRoot 'output/a-fixed-fixture-20261005') -Destination (Join-Path $taskPackage 'fixtures') -Recurse
Copy-Item -LiteralPath (Join-Path $taskRoot 'software/pc_pipeline/README.md') -Destination (Join-Path $taskPackage '使用与构建说明.md')
$taskSource=Join-Path $taskPackage 'source'
New-Item -ItemType Directory -Path $taskSource | Out-Null
foreach($taskDir in @('software/pc_pipeline','tools/a_pipeline','fpga/rtl/a_motion','fpga/sim/a_motion','fpga/projects/a_motion_td')){
  $taskTarget=Join-Path $taskSource (Split-Path -Parent $taskDir)
  New-Item -ItemType Directory -Force -Path $taskTarget | Out-Null
  Copy-Item -LiteralPath (Join-Path $taskRoot $taskDir) -Destination $taskTarget -Recurse
}
$taskLicenses=Join-Path $taskPackage 'licenses'
New-Item -ItemType Directory -Path $taskLicenses | Out-Null
$taskCvSource=Join-Path $taskRoot '.tools/opencv413/opencv/sources'
Get-ChildItem -LiteralPath $taskCvSource -Recurse -File | Where-Object {$_.Name -match '^(LICENSE|LICENCE|COPYING|NOTICE)(\.|$)'} | ForEach-Object {
  $taskRel=$_.FullName.Substring($taskCvSource.Length+1)
  $taskTarget=Join-Path $taskLicenses ('opencv/'+$taskRel)
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $taskTarget) | Out-Null
  Copy-Item -LiteralPath $_.FullName -Destination $taskTarget
}
Copy-Item -LiteralPath (Join-Path $taskBuild '_deps/json-src/LICENSE.MIT') -Destination (Join-Path $taskLicenses 'nlohmann-json-MIT.txt')
foreach($taskName in @('LGPL-3.0-only','GPL-3.0-only','BSD-3-Clause','Qt-GPL-exception-1.0')){
  Invoke-WebRequest ('https://raw.githubusercontent.com/qt/qtbase/v6.8.3/LICENSES/'+$taskName+'.txt') -OutFile (Join-Path $taskLicenses ($taskName+'.txt'))
}
@'
@echo off
cd /d "%~dp0"
start "" "%~dp0pipeline_gui.exe"
'@ | Set-Content -LiteralPath (Join-Path $taskPackage '启动回放界面.cmd') -Encoding ascii
@'
@echo off
cd /d "%~dp0"
"%~dp0pipeline_cli.exe" --input "%~dp0fixtures\manifest.json" --output "%~dp0results\fixture-%RANDOM%" --motion mock-dma
pause
'@ | Set-Content -LiteralPath (Join-Path $taskPackage '检查固定样例.cmd') -Encoding ascii
@'
[Paths]
Plugins=.
'@ | Set-Content -LiteralPath (Join-Path $taskPackage 'qt.conf') -Encoding ascii
@'
# A 双目处理工作台 1.0.1

双击“启动回放界面.cmd”。“导入截图包”选择含 export.json/pairs.csv/stereo 的父目录；原素材留在原位置。也可打开 fixtures/manifest.json 检查独立双眼人工图。播放、拖动寻帧、阶段选择、ROI 点击和导出均可使用。

运行 pipeline_cli.exe --help 查看命令。结果写到新目录；CPU 与模拟 DMA 共用完整七级整数核心。框回放、接口测试库和实际模型具有不同模式标记。

本包包含 Windows x64 程序、Qt/OpenCV/MSVC 动态运行库、源码、配置与人工样例。B/C 实际模块及设备 SDK 接入说明在 contracts/；详细验证记录及原始日志在 evidence/。本次无相机、AFH03、厂商 DMA/DDR3L SDK，未声称实物或三维/模型准确率通过。

Qt 6.8.3 共享库可以替换，使用 Qt 的 LGPL v3 条款及附带许可证；对应源码为 https://download.qt.io/archive/qt/6.8/6.8.3/submodules/qtbase-everywhere-src-6.8.3.tar.xz 。OpenCV 4.13.0 来源 https://github.com/opencv/opencv/releases/tag/4.13.0 ，第三方许可证在 licenses/opencv/。nlohmann JSON 3.11.3 为 MIT；MSVC 运行库来自本机 Visual Studio 可再分发目录。

源码中 source/software/pc_pipeline/README.md 的仓库相对报告入口由 evidence/ 中的交付报告替代。重建按源码说明准备固定依赖；Linux、TD 和验证脚本一并保留。
'@ | Set-Content -LiteralPath (Join-Path $taskPackage '开始使用.md') -Encoding utf8
Write-Host "Package staged: $taskPackage"
