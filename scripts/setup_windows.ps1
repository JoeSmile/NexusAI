# ContextGate — Windows 环境初始化 (PowerShell)
# 需要: Windows 10/11, 可选 Docker Desktop + NVIDIA 驱动 (vLLM / 多模态)
# 用法: pwsh -NoProfile -File scripts/setup_windows.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "== ContextGate Windows Setup ==" -ForegroundColor Cyan

# 1) uv
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv..." -ForegroundColor Yellow
    irm https://astral.sh/uv/install.ps1 | iex
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
uv --version

# 2) Python deps
Write-Host "uv sync --extra dev ..." -ForegroundColor Yellow
uv sync --extra dev

# 3) config.env
if (-not (Test-Path "config.env")) {
    Copy-Item "config.env.example" "config.env"
    Write-Host "Created config.env from example — edit LLM_API_KEY / DATABASE_URL" -ForegroundColor Green
} else {
    Write-Host "config.env already exists" -ForegroundColor DarkGray
}

# 4) Docker postgres
if (Get-Command docker -ErrorAction SilentlyContinue) {
    Write-Host "Starting postgres via docker compose..." -ForegroundColor Yellow
    docker compose -f docker-compose.local.yml up -d postgres
} else {
    Write-Host "Docker not found — install Docker Desktop or point DATABASE_URL to an existing Postgres." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Next:" -ForegroundColor Cyan
Write-Host "  uv run python scripts/seed_api_keys.py"
Write-Host "  uv run python scripts/seed_pgvector.py"
Write-Host "  pwsh -File scripts/run_windows.ps1"
Write-Host "Local vLLM example: set MODEL_REGISTRY_JSON to point base_url=http://127.0.0.1:8001/v1"
Write-Host "Done." -ForegroundColor Green
