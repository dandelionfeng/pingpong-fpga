param([switch]$NoGui,[switch]$NoTests,[switch]$Clean)
$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
& 'C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/Common7/Tools/Launch-VsDevShell.ps1' -Arch amd64 -HostArch amd64 -SkipAutomaticLocation
$env:VSLANG='1033'
$taskBuild=Join-Path $taskRoot 'build/a_pipeline_windows'
$taskQt=Join-Path $taskRoot '.tools/qt/6.8.3/msvc2022_64'
$taskCv=Join-Path $taskRoot '.tools/opencv413/opencv/build'
cmake -S (Join-Path $taskRoot 'software/pc_pipeline') -B $taskBuild -G Ninja -DCMAKE_BUILD_TYPE=Release "-DOpenCV_DIR=$taskCv" "-DCMAKE_PREFIX_PATH=$taskQt" "-DPIPELINE_BUILD_GUI=$(-not $NoGui)" "-DBUILD_TESTING=$(-not $NoTests)"
if($LASTEXITCODE){throw 'CMake configuration failed'}
if($Clean){cmake --build $taskBuild --clean-first --parallel 4}
else{cmake --build $taskBuild --parallel 4}
if($LASTEXITCODE){throw 'Build failed'}
$taskCvDll = Get-ChildItem -LiteralPath (Join-Path $taskCv 'x64') -Filter 'opencv_world4130.dll' -Recurse | Select-Object -First 1
if(-not $taskCvDll){throw 'OpenCV runtime DLL missing'}
Copy-Item -LiteralPath $taskCvDll.FullName -Destination $taskBuild -Force
if(-not $NoGui){& (Join-Path $taskQt 'bin/windeployqt.exe') --release --no-translations (Join-Path $taskBuild 'pipeline_gui.exe');if($LASTEXITCODE){throw 'Qt runtime deployment failed'}}
if(-not $NoTests){ctest --test-dir $taskBuild --output-on-failure;if($LASTEXITCODE){throw 'Core tests failed'}}
