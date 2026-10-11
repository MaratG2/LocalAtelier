param([int]$Port = 7870, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe') -or -not (Test-Path -LiteralPath 'frontend/dist/index.html')) {
    throw 'Run ./setup.ps1 first.'
}
$launcherArgs = @('start', '--port', "$Port")
if ($NoBrowser) { $launcherArgs += '--no-browser' }
& .venv/Scripts/python.exe launcher.py @launcherArgs
if ($LASTEXITCODE) { throw 'Could not start Local Atelier. See the launcher message above.' }
