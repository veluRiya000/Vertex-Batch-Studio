# Windows installer

Build from a clean Git checkout with Python 3.12+, Node.js 22.12+, stable Rust, and Visual Studio Build Tools (Desktop development with C++ and Windows SDK) installed:

```powershell
python -m venv .venv
powershell -ExecutionPolicy Bypass -File packaging/build-windows.ps1 -Python .venv/Scripts/python.exe
```

The x64 NSIS installer and SHA-256 checksum are written to `release/`. Python is bundled using PyInstaller; installed users do not need Python, Node.js or Rust. The Tauri shell uses the system WebView2 runtime. If it is missing, the installer downloads it; this is not an offline WebView2 installer.

Installed user configuration, imported credentials, images and runtime records live in `%APPDATA%/VertexBatchStudio/`, separate from the application binaries. Configure Google Cloud in Settings after first launch. Personal development credentials and batches are never included. Uninstalling retains user data.

The build is unsigned unless a signing certificate is configured separately.

## Validation

Run `cargo test --manifest-path frontend/src-tauri/Cargo.toml` from the repository root and `npm.cmd test` in `frontend/`.

Run the installed `vertex-batch-studio.exe --smoke-test` to exercise renderer loading, the local backend, PNG import and preview, task references and image count, appearance settings, SSE snapshots, maximize/restore, rejection of an unconfigured submission and local cancellation. It uses `%APPDATA%/VertexBatchStudio-smoke-test/` and never submits a cloud job or changes the startup entry. The success report is `.runtime/tauri-smoke.json` under that test directory. Remove any previous report before each run.

The native directory picker and Windows tray/startup behavior also require interactive checks. Closing to tray keeps the backend running; actual exit shuts down the backend spawned by this application. An independently started development server is left running.

For interactive verification, start `vertex-batch-studio.exe --ui-test`. This uses `%APPDATA%/VertexBatchStudio-install-test/` and a separate startup entry, leaving normal user configuration untouched.
