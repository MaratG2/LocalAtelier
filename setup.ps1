$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv from https://docs.astral.sh/uv/ first.' }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw 'Install Node.js 22 LTS or newer first.' }
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    & uv venv --python 3.14 .venv
    if ($LASTEXITCODE) { throw 'Could not create the application environment.' }
}
& uv pip install --python .venv/Scripts/python.exe -r requirements.txt
if ($LASTEXITCODE) { throw 'Could not install application dependencies.' }
Push-Location -LiteralPath frontend
try {
    & npm ci
    if ($LASTEXITCODE) { throw 'Could not install frontend dependencies.' }
    & npm run build
    if ($LASTEXITCODE) { throw 'Could not build the frontend.' }
} finally { Pop-Location }
Write-Host 'Local Atelier is ready. Open Start.cmd, then install models in the model library.' -ForegroundColor Green
