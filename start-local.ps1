param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required to create the local environment.' }
}
& '.\.venv\Scripts\python.exe' -m pip install --require-hashes -r requirements.lock
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; see the error above.' }
& '.\.venv\Scripts\python.exe' scripts\run_local.py
exit $LASTEXITCODE
