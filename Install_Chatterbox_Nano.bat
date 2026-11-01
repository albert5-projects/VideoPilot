@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m videopilot.install_nano
if errorlevel 1 echo Installation or generation test failed. Read the message above before retrying.
pause
