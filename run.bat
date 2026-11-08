@echo off
rem One-click launcher for Windows: creates a virtual environment on first run,
rem installs the requirements, then starts the helper. Extra arguments are passed on,
rem for example:  run.bat --comment "Great teaching" --chrome-version 138
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (
  where python >nul 2>nul
  if %errorlevel%==0 (set "PY=python") else (
    echo Python 3.9 or newer was not found. Install it from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" in the installer, then run this file again.
    pause
    exit /b 1
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo Could not create the virtual environment.
    pause
    exit /b 1
  )
)

echo Installing requirements (first run only takes a minute)...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo Installing requirements failed. Check your internet connection and try again.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" main.py %*
pause
