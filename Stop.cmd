@echo off
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" "%~dp0launcher.py" stop --no-browser %*
if errorlevel 1 pause
