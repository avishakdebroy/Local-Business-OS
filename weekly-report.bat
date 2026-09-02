@echo off
REM Generates the weekly report immediately and prints it.
REM Useful as a Windows Task Scheduler action if you prefer not to leave
REM the program running all week.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run start.bat once before using this.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m lbos.cli report
echo.
pause
