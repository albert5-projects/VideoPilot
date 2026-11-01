@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -c "from videopilot.flow_browser import open_browser; open_browser(); print('Inspection browser opened. Open the original Flow project and leave this browser open. No generation or import has been started.')"
if errorlevel 1 pause
