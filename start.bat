@echo off
REM ===========================================================================
REM  Local Business OS - double-click this file to start the program.
REM  It sets itself up the first time and starts normally after that.
REM ===========================================================================
setlocal
cd /d "%~dp0"
title Local Business OS

echo.
echo   ===========================================
echo     Local Business OS
echo   ===========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo   Python is not installed on this computer.
  echo.
  echo   1. Go to https://www.python.org/downloads/
  echo   2. Download Python 3.11 or newer.
  echo   3. During setup, TICK the box "Add python.exe to PATH".
  echo   4. Then double-click this file again.
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo   First-time setup: preparing the program folder...
  python -m venv .venv
  if errorlevel 1 (
    echo   Setup failed. Please send this window to whoever installed the program.
    pause
    exit /b 1
  )
  set NEEDS_INSTALL=1
)

set "PY=.venv\Scripts\python.exe"
if not exist ".venv\.installed" set NEEDS_INSTALL=1

if defined NEEDS_INSTALL (
  echo   Installing components. This happens once and takes a few minutes...
  "%PY%" -m pip install --upgrade pip --quiet
  "%PY%" -m pip install --quiet -e .
  if errorlevel 1 (
    echo   Installation failed. Check that this computer can reach the internet.
    pause
    exit /b 1
  )
  echo ok> ".venv\.installed"
)

if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo   Created your settings file ^(.env^).
)

echo   Checking the database...
"%PY%" -m lbos.cli migrate
if errorlevel 1 (
  echo   The database could not be prepared. Nothing has been changed.
  pause
  exit /b 1
)

echo.
echo   Starting. Your browser will open in a moment.
echo.
echo   * Keep this black window open while you work.
echo   * To stop the program, close this window.
echo.
start "" http://127.0.0.1:8000
"%PY%" -m lbos.cli serve

echo.
echo   The program has stopped.
pause
