@echo off
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Run setup.ps1 once before starting Local Atelier.
  pause
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0launcher.py" start %*
if errorlevel 1 pause
