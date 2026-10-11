@echo off
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" "%~dp0launcher.py" restart %*
if errorlevel 1 pause
