@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0infrastructure\windows_runtime.ps1" update %*
set "result=%errorlevel%"
pause
exit /b %result%
