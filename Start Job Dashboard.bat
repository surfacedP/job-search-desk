@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo The project Python environment was not found.
  echo Run the original setup steps first, then try again.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" app.py

