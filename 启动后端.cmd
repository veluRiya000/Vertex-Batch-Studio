@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. See README.md for setup instructions.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 -m backend serve
if errorlevel 1 pause
