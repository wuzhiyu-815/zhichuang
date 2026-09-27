@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
".venv\Scripts\python.exe" -m infrastructure.system_update update %*
set "result=%errorlevel%"
pause
exit /b %result%
