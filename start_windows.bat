@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if not defined SHORT_DRAMA_MULTIUSER set "SHORT_DRAMA_MULTIUSER=0"
if not defined SHORT_DRAMA_PORT set "SHORT_DRAMA_PORT=7860"
set "PATH=%~dp0tools\ffmpeg;%PATH%"
if exist ".venv\Scripts\python.exe" goto run
where py >nul 2>nul
if errorlevel 1 goto missing_python
py -3 -m venv .venv
if errorlevel 1 goto failed
:run
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Zhichuang build 20260926-082135 - http://127.0.0.1:%SHORT_DRAMA_PORT%
".venv\Scripts\python.exe" -u app.py
if errorlevel 1 goto failed
pause
exit /b 0
:missing_python
echo Install Python 3.11 or 3.12 with the Python Launcher, then try again.
pause
exit /b 1
:failed
echo Startup failed. Please keep this window open and copy the error above.
pause
exit /b 1
