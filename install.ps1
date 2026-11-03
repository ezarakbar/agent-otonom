# AGENT OTONOM — Windows installer
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "==> AGENT OTONOM installer"
Write-Host "    root: $Root"

function Need-Cmd($name) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    throw "Missing dependency: $name"
  }
}

Need-Cmd python
Need-Cmd ffmpeg

python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip wheel
& .\.venv\Scripts\python.exe -m pip install -e .

if (-not (Test-Path .env)) {
  Copy-Item .env.example .env
}

New-Item -ItemType Directory -Force -Path outputs, jobs, logs, uploads, "workflows\_generated", "models\piper" | Out-Null

Write-Host "==> Doctor"
& .\.venv\Scripts\python.exe -m agent_otonom doctor

Write-Host ""
Write-Host "Done. Run:"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  agent-otonom serve"
Write-Host "  # open http://127.0.0.1:8790"
