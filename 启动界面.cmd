@echo off
chcp 65001 >nul
cd /d "%~dp0frontend"
if not exist "node_modules\@tauri-apps\cli" (
  echo Frontend dependencies are missing. Run npm ci in frontend.
  pause
  exit /b 1
)
where cargo >nul 2>nul
if errorlevel 1 (
  echo Rust and Visual Studio C++ Build Tools are required for source desktop builds.
  pause
  exit /b 1
)
call npm.cmd run desktop
if errorlevel 1 pause
