@echo off
REM Makes a full backup immediately, including receipt photos.
REM Safe to run while the program is open.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run start.bat once before using this.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m lbos.cli backup --full
echo.
pause
