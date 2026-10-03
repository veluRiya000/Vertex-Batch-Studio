@echo off
chcp 65001 >nul
cd /d "%~dp0frontend"
if not exist "node_modules\electron\dist\electron.exe" (
  echo Frontend dependencies are missing. Run npm install in frontend.
  pause
  exit /b 1
)
call npm.cmd run build
if errorlevel 1 (
  pause
  exit /b 1
)
powershell.exe -NoProfile -Command "Start-Process -FilePath '.\node_modules\electron\dist\electron.exe' -ArgumentList '.' -WorkingDirectory (Get-Location).Path -WindowStyle Hidden"
