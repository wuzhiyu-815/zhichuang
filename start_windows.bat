@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0infrastructure\windows_runtime.ps1" run
if errorlevel 1 goto failed
pause
exit /b 0
:failed
echo Startup failed. Please keep this window open and copy the error above.
pause
exit /b 1
