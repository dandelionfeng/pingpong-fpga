@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_td_smoke.ps1" %*
exit /b %errorlevel%
