@echo off
REM Makes a full backup immediately, including receipt photos.
REM Safe to run while the program is open.
setlocal
cd /d "%~dp0"
REM Bengali text needs a UTF-8 console; cmd.exe defaults to a legacy code page.
chcp 65001 >nul
if not exist ".venv\Scripts\python.exe" (
  echo Run start.bat once before using this.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m lbos.cli backup --full
echo.
pause
