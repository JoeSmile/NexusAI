#!/usr/bin/env bash
# Agent 模块 QA(MANUAL_TEST §7,7.1-7.5)
# 用法: QA_KEY=<user key> ./examples/qa/07-agent/agent_qa.sh
set -u

BASE="${QA_BASE:-localhost:8000}"
KEY="${QA_KEY:-${RAG_QA_KEY:-}}"
UID_="${QA_UID:-qa_agent_user}"
LOG="data/qa/agent_qa_$(date +%Y%m%d_%H%M%S).log"
mkdir -p data/qa

[ -z "$KEY" ] && echo "缺少 QA_KEY" >&2 && exit 2

PASS=0; FAIL=0
say() { echo "$@" | tee -a "$LOG"; }
ok()  { PASS=$((PASS+1)); say "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); say "  ❌ $1"; }
code() { curl -s -o /tmp/ag_body.$$ -w "%{http_code}" -H "X-API-Key: $KEY" "$@"; }

say "=== Agent QA $(date '+%F %T') ==="

# 7.1 多轮对话
C=$(code -X POST "$BASE/agent/chat" -H "Content-Type: application/json" \
  -d "{\"user_id\":\"$UID_\",\"message\":\"你好,介绍一下你自己\"}")
if [ "$C" = 200 ] && grep -qE "response|reply|content" /tmp/ag_body.$$; then
  ok "7.1 多轮对话 200"
else
  bad "7.1 agent/chat http=$C"
fi

# 7.2 记忆读取
C=$(code "$BASE/agent/memory/$UID_")
if [ "$C" = 200 ]; then
  ok "7.2 memory 读取 200"
else
  bad "7.2 memory http=$C"
fi

# 7.3 工具列表
C=$(code "$BASE/agent/tools")
if [ "$C" = 200 ] && python3 -c "import json;d=json.load(open('/tmp/ag_body.$$'));assert len(d.get('data',d.get('tools',[])) or [])>0" 2>/dev/null; then
  ok "7.3 tools 非空"
else
  bad "7.3 tools http=$C 或为空"
fi

# 7.4 回访
C=$(code -X POST "$BASE/agent/followup" -H "Content-Type: application/json" -d "{\"user_id\":\"$UID_\"}")
if [ "$C" = 200 ]; then
  ok "7.4 followup 200"
else
  bad "7.4 followup http=$C"
fi

# 7.5 历史
C=$(code "$BASE/agent/history/$UID_")
if [ "$C" = 200 ]; then
  ok "7.5 history 200"
else
  bad "7.5 history http=$C"
fi

say ""
say "=== 结果: PASS=$PASS FAIL=$FAIL | 证据: $LOG ==="
rm -f /tmp/ag_body.$$ 2>/dev/null
[ "$FAIL" = 0 ]
