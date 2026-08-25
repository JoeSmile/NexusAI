# NexusAI 本地一键启动（解决端口冲突/幽灵端口/依赖未就绪）
# 用法: powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev_up.ps1 [-SkipDeps] [-OnlyBackend]
param(
    [switch]$SkipDeps,      # 跳过 docker 依赖启动（已起过）
    [switch]$OnlyBackend    # 只起后端（前端自己起）
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "═══ NexusAI 本地启动 ═══" -ForegroundColor Cyan

# 1) 检查并清理 8000 端口（幽灵端口/残留实例）
$conns = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($conns) {
    foreach ($c in $conns) {
        $pidToKill = $c.OwningProcess
        $proc = Get-Process -Id $pidToKill -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "  杀掉占用 8000 的进程: $($proc.ProcessName) (PID $pidToKill)" -ForegroundColor Yellow
            Stop-Process -Id $pidToKill -Force
        } else {
            Write-Host "  8000 存在幽灵占用 (PID $pidToKill 已不存在)，等待释放..." -ForegroundColor Yellow
        }
    }
    Start-Sleep -Seconds 2
}
if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "  ⚠ 8000 仍被占用（可能需重启机器释放）——改为使用 8001" -ForegroundColor Red
    $port = 8001
} else {
    $port = 8000
}

# 2) 依赖（docker）
if (-not $SkipDeps) {
    Write-Host "1/5 检查 Docker daemon..." -ForegroundColor Cyan
    docker info *> $null
    if ($LASTEXITCODE -ne 0) { Write-Host "  ✗ Docker Desktop 未运行，请先启动" -ForegroundColor Red; exit 1 }
    Write-Host "2/5 启动 postgres + redis..." -ForegroundColor Cyan
    docker compose -f docker-compose.local.yml up -d postgres redis
    # 等 postgres healthy（最多 60s）
    Write-Host "3/5 等待依赖就绪..." -ForegroundColor Cyan
    $ok = $false
    for ($i = 0; $i -lt 30; $i++) {
        if ((docker compose -f docker-compose.local.yml ps --format "{{.Name}} {{.Health}}" | Select-String "healthy").Count -ge 2) { $ok = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $ok) { Write-Host "  ✗ 依赖未 healthy（docker compose ps 查看）" -ForegroundColor Red; exit 1 }
}

# 3) 迁移 + seed
Write-Host "4/5 迁移 + seed..." -ForegroundColor Cyan
uv run alembic upgrade head
uv run python scripts/seed_api_keys.py
uv run python scripts/seed_capabilities.py

# 4) 起后端
Write-Host "5/5 启动后端 :$port ..." -ForegroundColor Cyan
Write-Host "  后端: http://127.0.0.1:$port/docs  前端: cd frontend && npm run dev" -ForegroundColor Green
uv run uvicorn backend.app:app --reload --port $port
