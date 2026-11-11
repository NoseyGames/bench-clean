# Bench Clean

A Windows utility that opens a private dashboard on `127.0.0.1`. Review optional bundled apps, explore storage, and see which processes use CPU, RAM, and GPU resources.

**Early release:** inventory, monitoring, storage scanning, request security, and browser behavior have been checked locally. Real app removal has **not** been exercised on a disposable Windows installation yet. Review the removal list and save app data before using uninstall.

## Download

Get **BenchClean.exe** from the [early-release downloads](https://github.com/NoseyGames/bench-clean/releases/tag/v0.1.0). Run it as your normal Windows user; Python is bundled. The executable is unsigned. Its SHA-256 checksum is included with the release.

## Run from source

1. Install **Python 3.12 or newer** from [python.org](https://www.python.org/downloads/windows/), including the Python launcher.
2. Download this repository using **Code → Download ZIP**, then extract the entire folder.
3. Double-click **Start.cmd**. The launcher creates a local `.venv`, installs the pinned `psutil` dependency from PyPI, and opens your browser.
4. Review **Remove extras**. Select only the apps you want removed, then confirm. You can skip this step.
5. Continue to **Storage explorer**, **Live processes**, or **Installed apps**.

Run as your normal Windows account. The server itself does not need administrator rights. A desktop uninstaller may show its own UAC prompt; use **Windows Installed apps** if an uninstaller cannot launch.

Keep the launcher window open. **End local session** stops the server; closing the browser alone does not. Ctrl+C also stops it. Do not interrupt an active removal job.

The source launcher requires internet access to obtain its dependency on first run. Dashboard assets and runtime telemetry stay on the machine; there are no external fonts, analytics, or CDN scripts.

## Features and boundaries

- **Remove extras:** explicit, curated list of optional Microsoft/Clipchamp Store packages. No automatic selections. This is not a detector for every OEM trial app; use Installed apps for those.
- **Installed apps:** current-user Store packages plus desktop uninstall registrations in 32/64-bit HKCU/HKLM. Protected Store infrastructure/framework packages are excluded from removal. No `Win32_Product` query or MSI repair enumeration.
- **Uninstall:** Store removal is current-user only, with a post-removal check. It does not remove provisioning for future users. Desktop actions open the registered uninstaller and report **launched**, never assume it finished. Refresh inventory after completing its prompts. Unsupported script/ambiguous uninstall commands fall back to Windows Installed apps.
- **Storage:** drive capacity, asynchronous directory totals, drill-down, largest 100 files, progress, and cancellation. No file deletion. A complete drive scan may take a long time and use disk resources.
- **Processes:** PID, normalized CPU utilization, resident working-set RAM, and busiest GPU engine. Sorting, filtering, and pause controls. Install-path matching enables app uninstall from a process row where identification is unambiguous. A process is not itself an installed app; unmatched processes have no uninstall button.
- **GPU:** Windows GPU engine performance counters, sampled roughly every four seconds. Driver/OS permissions can make them unavailable. No dedicated VRAM figure. CPU/RAM sample every two seconds; new processes need a second sample for CPU. Numbers can differ from Task Manager's calculation and timing.

File totals are logical lengths. Access-denied folders and reparse points (junctions, symlinks, and some cloud placeholders) are skipped and counted. Hard links can be counted multiple times; sparse/compressed files differ from physical allocation. Disk usage includes protected/system data that normal-user scans cannot enumerate. Process working sets can also overlap because memory may be shared.

## Security and recovery

The server binds only to `127.0.0.1` on a free port. An unpredictable session token is passed in the browser URL fragment, moved to tab session storage, and sent in a custom header. Host and Origin checks reject foreign origins/rebinding hosts. All mutations require authenticated JSON POSTs; uninstall additionally requires a confirmation flag and an inventory identifier. Raw commands from the browser are never executed. Uninstall strings come from local Windows registry entries and are passed to the OS without a command shell.

This is a local-user tool, not a security boundary against malware already running as your Windows user. Do not share the launcher URL. Keep the session closed when not needed. It does not change Defender, firewall, Windows Update, services, startup settings, or registry performance tweaks.

Removal is **not reversible by this utility**. Store app data may be lost. Reinstall Store apps through Microsoft Store and desktop apps from their publisher; restored app binaries do not guarantee restored data. Local action logs rotate under `%LOCALAPPDATA%\BenchClean\actions.log`. They contain app names and results; review before sharing.

To remove Bench Clean itself: end the session, delete the extracted folder (including `.venv`), and optionally delete `%LOCALAPPDATA%\BenchClean`. There is no service, scheduled task, or startup entry.

## Development and portable build

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe app.py
```

Optional executable build (Python is bundled; end users do not need to install it):

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller==6.16.0
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --name BenchClean --add-data "web;web" --add-data "scripts;scripts" app.py
```

Output: `dist\BenchClean.exe`. Builds are unsigned. Windows CI runs checks and uploads the portable executable as an Actions artifact. An Actions artifact requires a GitHub login to download; the source ZIP is public. Only claim a downloadable executable after the workflow has succeeded.

Architecture: `app.py` owns HTTP authentication, job serialization, sampling and lifecycle; `system.py` owns Windows inventory and uninstall integration; `storage.py` owns bounded top-file tracking and scan state; `scripts/` contains fixed PowerShell operations; `web/` contains the buildless UI. Worker threads publish snapshots under locks. Only one removal job and one storage scan can run at a time.

## Platform references

- [Microsoft: Remove-AppxPackage](https://learn.microsoft.com/en-us/powershell/module/appx/remove-appxpackage) — current-user package removal.
- [Microsoft: uninstall registry properties](https://learn.microsoft.com/en-us/windows/win32/msi/uninstall-registry-key) — desktop uninstall inventory.
- [Microsoft DirectX: GPUs in Task Manager](https://devblogs.microsoft.com/directx/gpus-in-the-task-manager/) — busiest-engine GPU interpretation.

See [VALIDATION.md](VALIDATION.md) for the exact checks and remaining limits.
