@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\pythonw.exe" (
 echo Please run Setup.bat first.
 pause
 exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m videopilot.gui
exit /b
