@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Run Setup.bat first.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" -m pip install "playwright>=1.56,<2"
if errorlevel 1 (
 echo Browser setup failed. Check your Internet connection and try again.
 pause
 exit /b 1
)
echo.
echo Ready. Restart VideoPilot. In Flow images choose Open Flow / sign in.
echo Sign in directly in that browser, CLOSE it, then choose Run Flow queue.
echo No extension or extra Chromium download is needed; installed Chrome/Edge is used.
pause
