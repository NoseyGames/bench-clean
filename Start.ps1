$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    $python = Get-Command py.exe -ErrorAction SilentlyContinue
    if (-not $python) { throw 'Install Python 3.12 or newer from python.org (include the Python launcher), then run Start.cmd again.' }
    & py.exe -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
}
& .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check your internet connection.' }
& .\.venv\Scripts\python.exe app.py
exit $LASTEXITCODE
