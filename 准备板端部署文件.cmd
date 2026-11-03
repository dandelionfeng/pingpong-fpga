@echo off
cd /d "%~dp0"
"runtime\python\python.exe" -B "tools\restore_rk_wheels.py"
pause
