# Windows installer

Build from a clean Git checkout with Python 3.12+ and Node.js installed:

```powershell
python -m venv .venv
powershell -ExecutionPolicy Bypass -File packaging/build-windows.ps1 -Python .venv/Scripts/python.exe
```

The x64 NSIS installer is written to `release/`. Python is bundled using PyInstaller; installed users do not need Python or Node.js.

Installed user configuration, imported credentials, images and runtime records live in `%APPDATA%/VertexBatchStudio/`, separate from the application binaries. Configure Google Cloud in Settings after first launch. Personal development credentials and batches are never included. Uninstalling retains user data.

The build is unsigned unless a signing certificate is configured separately.
