#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 停止旧进程
pkill -f "uvicorn backend.app" 2>/dev/null

# 等待进程完全停止
sleep 3

# 启动后端
cd "$PROJECT_ROOT"
mkdir -p log
nohup uv run --no-sync uvicorn backend.app:app --host 0.0.0.0 --port 8000 > log/backend.log 2>&1 &
echo "后端启动中..."

# 等待后端启动
sleep 5

# 检查服务状态
echo ""
echo "===== 服务状态 ====="
ps aux | grep -E "uvicorn backend.app" | grep -v grep
echo ""
echo "===== 端口监听 ====="
ss -tlnp | grep -E ":8000" 2>/dev/null || netstat -tlnp | grep -E ":8000" 2>/dev/null
echo ""
echo "服务启动完成！"
echo "后端地址: http://localhost:8000"
