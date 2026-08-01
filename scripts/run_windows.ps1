# ContextGate — 启动 API (Windows)
# 用法: pwsh -NoProfile -File scripts/run_windows.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv not found. Run scripts/setup_windows.ps1 first."
}

if (-not $env:DATABASE_URL) {
    $env:DATABASE_URL = "postgresql://contextgate:contextgate_local@localhost:5432/contextgate"
}

Write-Host "Starting uvicorn on http://0.0.0.0:8000 ..." -ForegroundColor Cyan
Write-Host "Playground: http://localhost:8000/playground/"
Write-Host "Optional local LLM: vLLM/ollama OpenAI-compatible at :8001 — register via MODEL_REGISTRY_JSON"

uv run --no-sync uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000
