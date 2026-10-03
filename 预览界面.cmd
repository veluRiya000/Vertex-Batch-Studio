@echo off
chcp 65001 >nul
cd /d "%~dp0frontend"
node scripts/preview.cjs
if errorlevel 1 pause
