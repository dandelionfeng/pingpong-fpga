@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_and_test.ps1" %*
exit /b %errorlevel%
