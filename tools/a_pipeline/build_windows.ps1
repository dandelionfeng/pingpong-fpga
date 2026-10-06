param([switch]$NoGui,[switch]$NoTests,[switch]$Clean,[string]$DependenciesRoot='')
$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
& 'C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/Common7/Tools/Launch-VsDevShell.ps1' -Arch amd64 -HostArch amd64 -SkipAutomaticLocation
$env:VSLANG='1033'
$taskBuild=Join-Path $taskRoot 'build/a_pipeline_windows'
cmake -S (Join-Path $taskRoot 'software/pc_pipeline') -B $taskBuild -G Ninja -DCMAKE_BUILD_TYPE=Release "-DPIPELINE_DEPENDENCIES_ROOT=$DependenciesRoot" "-DPIPELINE_BUILD_GUI=$(-not $NoGui)" "-DBUILD_TESTING=$(-not $NoTests)"
if($LASTEXITCODE){throw 'CMake configuration failed'}
if($Clean){cmake --build $taskBuild --clean-first --parallel 4}
else{cmake --build $taskBuild --parallel 4}
if($LASTEXITCODE){throw 'Build failed'}
# CMake deploys OpenCV and Qt runtime files for both script and IDE builds.
if(-not $NoTests){ctest --test-dir $taskBuild --output-on-failure;if($LASTEXITCODE){throw 'Core tests failed'}}
