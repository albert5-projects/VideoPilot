@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
where py >nul 2>nul
if errorlevel 1 (
 echo Install Python 3.11 or 3.12 for Windows from python.org first, including the launcher and tkinter.
 pause
 exit /b 1
)
py -3.11 -c "import sys" >nul 2>nul
if errorlevel 1 (
 py -3.12 -m venv .venv
) else (
 py -3.11 -m venv .venv
)
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m videopilot.doctor
if errorlevel 1 goto fail
echo.
echo Setup complete. Run Download_Models.bat once, then Launch.bat.
echo Your existing Codex sign-in is reused. No new login is needed.
pause
exit /b 0
:fail
echo Setup failed. Read the message above. No CapCut files were changed.
pause
exit /b 1
