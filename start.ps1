param([int]$Port = 7870, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe') -or -not (Test-Path -LiteralPath 'frontend/dist/index.html')) {
    throw 'Run ./setup.ps1 first.'
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port is already in use. Open the running app, or choose ./start.ps1 -Port 7871."
}
Write-Host "Local Atelier: http://127.0.0.1:$Port/  |  Ctrl+C stops the studio and its GPU workers." -ForegroundColor Green
if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port/" }
& .venv/Scripts/python.exe -u run.py --port $Port
