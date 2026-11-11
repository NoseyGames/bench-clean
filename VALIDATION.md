# Validation record

Local checks performed November 10, 2026 on Windows with Python 3.12.10 and psutil 7.2.2.

- Python compilation and JavaScript syntax check passed.
- All 18 automated tests passed. The suite exercises loopback token authentication, foreign Origin and Host rejection, private command redaction, explicit uninstall confirmation, traversal rejection, network scan rejection, unknown endpoints, malformed payloads, protected/missing app rejection, removal-job serialization, Windows MSI command parsing, shell-command rejection, install-path boundary/ambiguity matching, storage totals/ranking, and cancellation.
- Initial sandbox execution could not connect to loopback or create normal temporary fixtures. Re-running outside the sandbox passed; this was an execution restriction, not evidence of app removal.
- Live Windows inventory returned 125 app entries with no warnings, roughly 300 processes, and available GPU counters. The optional-app allowlist matched zero installed packages on this account.
- Browser inspection confirmed the cleanup empty state, live CPU/RAM/GPU/PID rows, install-path app matches, process filtering, and a completed read-only scan of the three web assets with zero skipped items.
- PyInstaller 6.16.0 built the portable Windows x64 executable. The executable started, served the dashboard with HTTP 200, and returned 125 apps, 305 visible processes, available GPU counters, and no inventory warnings. This is a development-machine smoke test, not clean-install or uninstall validation.

Not established: real Store or desktop uninstallation, desktop UAC flows, app reinstallation/data recovery, end-to-end bootstrap on a fresh Windows installation, Windows 10 compatibility, multi-GPU accuracy, ARM builds, full-disk scans, or behavior under enterprise policy. The portable build workflow does not substitute for testing an executable on a clean machine.

Next destructive test belongs in a disposable Windows VM: install a known disposable Store app and a small desktop MSI app; select each, confirm removal, verify its inventory entry disappears, check logs, and reinstall. Also exercise cancellation, denied elevation, missing uninstaller, and non-removable Store package behavior. No apps were uninstalled from the development machine.
