# Quick restart (Windows development preview)

Double-click `Restart-Studio.cmd` in the repository root to restart the current
development preview. The launcher uses `.runtime/VertexStudio-latest.exe`, the
repository Python environment, and the existing `.runtime/desktop-links-preview`
data directory. It does not build the app, reinstall it, or update an installed
production copy. If a development update has been staged as
`.runtime/VertexStudio-pending.exe` with a SHA-256 manifest, a successful guarded
restart verifies and applies it before opening the window. `-CheckOnly` does not
apply pending updates.

The script checks active image/Harness requests and available browser draft state.
It gracefully stops this profile's Harness and Python backend, closes only the
matching preview executable, and opens a fresh window. Harness mode and offline
mode are restored when the preview's local debug connection is available. Sessions,
credentials, uploaded attachments, output files and the persona setting stay in
the existing data directory. No Batch submit or cancel endpoint is called.

```powershell
.\Restart-Studio.ps1 -CheckOnly
.\Restart-Studio.ps1
.\Restart-Studio.ps1 -Force
```

`-CheckOnly` inspects without restarting. Normal restart refuses active requests
or detected unsaved input. `-Force` explicitly skips those checks; unsent input
can be lost and local Agent work stops. Cloud jobs are not cancelled by restart.
For a different preview data profile, pass `-DataDirectory` with its absolute path.

The CMD launcher uses an execution-policy bypass for this single PowerShell
process; it does not change the machine's PowerShell policy. The script never
prints local authentication tokens and does not modify credentials. It refuses
to operate on a backend reporting a different data directory or on multiple
windows using the same preview executable. Other installed apps are untouched.
