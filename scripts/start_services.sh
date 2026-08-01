#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_ROOT/log"

mkdir -p "$LOG_DIR"

echo "=========================================="
echo "ContextGate 服务启动"
echo "=========================================="

cd "$PROJECT_ROOT"
echo "启动后端服务..."
nohup /usr/local/bin/python3.10 run_backend.py > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo "$BACKEND_PID" > "$LOG_DIR/backend.pid"
echo "后端启动中，PID: $BACKEND_PID"

sleep 3

echo "=========================================="
echo "后端: http://localhost:8000"
echo "API 文档: http://localhost:8000/docs"
echo "测试页: http://localhost:8000/playground/playground.html"
echo "后端日志: $LOG_DIR/backend.log"
echo "=========================================="
