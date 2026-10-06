[CmdletBinding()]
param(
    [string]$OpenCVDir,
    [string]$VisualStudioPath,
    [string]$BuildDirectory
)

$ErrorActionPreference = 'Stop'
if (-not $BuildDirectory) { $BuildDirectory = Join-Path $PSScriptRoot 'build-ninja-release' }
$taskRoot = Split-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) -Parent
if (-not $OpenCVDir) {
    if ($env:OpenCV_DIR) {
        $OpenCVDir = $env:OpenCV_DIR
    } else {
        $OpenCVDir = Join-Path $taskRoot '.tools\opencv-4.10.0\opencv\build\x64\vc16\lib'
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $OpenCVDir 'OpenCVConfig.cmake'))) {
    throw 'OpenCVConfig.cmake not found. Pass -OpenCVDir <OpenCV CMake directory>.'
}
if (-not $VisualStudioPath) {
    $taskVswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path -LiteralPath $taskVswhere)) {
        throw 'vswhere.exe not found. Pass -VisualStudioPath <Visual Studio installation>.'
    }
    $VisualStudioPath = & $taskVswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if ($LASTEXITCODE -ne 0 -or -not $VisualStudioPath) { throw 'No Visual Studio C++ installation found.' }
}
$taskDevCmd = Join-Path $VisualStudioPath 'Common7\Tools\VsDevCmd.bat'
$taskCmake = Join-Path $VisualStudioPath 'Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'
$taskNinja = Join-Path $VisualStudioPath 'Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe'
$taskCtest = Join-Path (Split-Path $taskCmake -Parent) 'ctest.exe'
foreach ($taskTool in @($taskDevCmd, $taskCmake, $taskNinja, $taskCtest)) {
    if (-not (Test-Path -LiteralPath $taskTool)) { throw "Missing build tool: $taskTool" }
}

# Import only compiler variables; restore them on completion. Windows cmd can emit
# both PATH and Path. Use the uppercase compiler PATH rather than the older copy.
$taskCompilerVariables = @('INCLUDE', 'LIB', 'LIBPATH', 'VCToolsInstallDir', 'VCToolsVersion',
    'VSINSTALLDIR', 'VCINSTALLDIR', 'WindowsSdkDir', 'WindowsSDKVersion',
    'UniversalCRTSdkDir', 'UCRTVersion', 'VSCMD_ARG_TGT_ARCH', 'VSCMD_ARG_HOST_ARCH', 'VSLANG')
$taskPreviousEnvironment = @{}
foreach ($taskName in ($taskCompilerVariables + 'PATH')) {
    $taskPreviousEnvironment[$taskName] = [Environment]::GetEnvironmentVariable($taskName, 'Process')
}
$taskExitCode = 0
try {
    $env:VSLANG = '1033'
    $taskCommand = '"' + $taskDevCmd + '" -no_logo -arch=x64 -host_arch=x64 >nul && set'
    $taskEnvironment = & $env:ComSpec /d /s /c $taskCommand
    if ($LASTEXITCODE -ne 0) { throw 'MSVC environment initialization failed.' }
    foreach ($taskLine in $taskEnvironment) {
        if ($taskLine -match '^([^=]+)=(.*)$' -and $taskCompilerVariables -contains $Matches[1]) {
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process')
        }
    }
    $taskCompilerPath = @($taskEnvironment | Where-Object { $_ -cmatch '^PATH=' })
    if ($taskCompilerPath.Count -eq 1) {
        $env:PATH = $taskCompilerPath[0].Substring(5)
    } else {
        $taskCompilerPath = @($taskEnvironment | Where-Object { $_ -match '^PATH=' })
        if ($taskCompilerPath.Count -ne 1) { throw 'Could not identify the MSVC PATH.' }
        $env:PATH = $taskCompilerPath[0].Substring(5)
    }
    $taskCompiler = Join-Path $env:VCToolsInstallDir 'bin\Hostx64\x64\cl.exe'
    if (-not (Test-Path -LiteralPath $taskCompiler)) { throw 'x64 cl.exe not found.' }

    # OpenCV's Windows binary package puts the DLLs beside its lib directory.
    $taskOpenCVBin = Join-Path (Split-Path $OpenCVDir -Parent) 'bin'
    $env:PATH = "$taskOpenCVBin;$(Split-Path $taskNinja -Parent);$(Split-Path $taskCmake -Parent);$env:PATH"
    New-Item -ItemType Directory -Path $BuildDirectory -Force | Out-Null
    $BuildDirectory = (Resolve-Path -LiteralPath $BuildDirectory).Path
    @(
        "MSVC=$((Get-Item -LiteralPath $taskCompiler).VersionInfo.FileVersion)"
        "WindowsSDK=$env:WindowsSDKVersion"
        "OpenCVDir=$OpenCVDir"
        "Source=$PSScriptRoot"
        "Build=$BuildDirectory"
        (& $taskCmake --version | Select-Object -First 1)
        "Ninja=$(& $taskNinja --version)"
    ) | Set-Content -LiteralPath (Join-Path $BuildDirectory 'tool-versions.txt') -Encoding UTF8

    & $taskCmake -S $PSScriptRoot -B $BuildDirectory -G Ninja '-DCMAKE_BUILD_TYPE=Release' `
        '-DBUILD_TESTING=ON' "-DCMAKE_CXX_COMPILER=$taskCompiler" `
        "-DCMAKE_MAKE_PROGRAM=$taskNinja" "-DOpenCV_DIR=$OpenCVDir" 2>&1 |
        Tee-Object -FilePath (Join-Path $BuildDirectory 'configure.log')
    if ($LASTEXITCODE -ne 0) { throw "CMake configure failed: $LASTEXITCODE" }
    # The Chinese MSVC /showIncludes prefix can be decoded differently by
    # Ninja/CMake in this shell. Clean this small target to avoid stale objects
    # when headers change. Source files are never deleted by this build step.
    & $taskCmake --build $BuildDirectory --clean-first --parallel 2 2>&1 |
        Tee-Object -FilePath (Join-Path $BuildDirectory 'build.log')
    if ($LASTEXITCODE -ne 0) { throw "C++ build failed: $LASTEXITCODE" }
    & $taskCtest --test-dir $BuildDirectory --output-on-failure --verbose 2>&1 |
        Tee-Object -FilePath (Join-Path $BuildDirectory 'test.log')
    if ($LASTEXITCODE -ne 0) { throw "C++ test failed: $LASTEXITCODE" }
    Write-Output 'CPP_BUILD_AND_TEST_PASS'
} catch {
    $taskExitCode = 1
    Write-Warning $_.Exception.Message
} finally {
    foreach ($taskName in $taskPreviousEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($taskName, $taskPreviousEnvironment[$taskName], 'Process')
    }
}
exit $taskExitCode
