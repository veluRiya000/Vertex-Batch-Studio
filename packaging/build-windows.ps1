param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path $PSScriptRoot -Parent
Set-Location $sourceRoot
& $Python -m pip install -r requirements.lock.txt pyinstaller==6.22.3
if ($LASTEXITCODE) { throw 'Python dependencies failed' }
& $Python -m PyInstaller --noconfirm --clean --onedir --name vertex-backend --paths $sourceRoot --distpath packaging/backend --workpath packaging/work --specpath packaging --collect-submodules uvicorn --collect-submodules google.genai --collect-submodules google.cloud.storage --copy-metadata fastapi --copy-metadata uvicorn --copy-metadata Pillow --copy-metadata google-genai --copy-metadata google-cloud-storage packaging/backend_entry.py
if ($LASTEXITCODE) { throw 'Backend packaging failed' }
Set-Location (Join-Path $sourceRoot 'frontend')
& npm.cmd ci
if ($LASTEXITCODE) { throw 'Frontend dependencies failed' }
& npm.cmd run package:win
if ($LASTEXITCODE) { throw 'Installer packaging failed' }
