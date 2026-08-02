#!/usr/bin/env bash
# 冒烟 QA(MANUAL_TEST §1,1.1-1.5)
# 用法: QA_USER_KEY=<user key> QA_SUPER_KEY=<super_admin key> ./examples/qa/01-smoke/smoke_qa.sh
set -u

BASE="${QA_BASE:-localhost:8000}"
USER_KEY="${QA_USER_KEY:-${RAG_QA_KEY:-}}"
SUPER_KEY="${QA_SUPER_KEY:-}"
LOG="data/qa/smoke_qa_$(date +%Y%m%d_%H%M%S).log"
mkdir -p data/qa

[ -z "$USER_KEY" ] && echo "缺少 QA_USER_KEY" >&2 && exit 2
[ -z "$SUPER_KEY" ] && echo "缺少 QA_SUPER_KEY(1.5 需要)" >&2 && exit 2

PASS=0; FAIL=0
say() { echo "$@" | tee -a "$LOG"; }
ok()  { PASS=$((PASS+1)); say "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); say "  ❌ $1"; }
code() { curl -s -o /tmp/smoke_body.$$ -w "%{http_code}" "$@"; }

say "=== 冒烟 QA $(date '+%F %T') ==="

# 1.1 根路径
C=$(code "$BASE/")
if [ "$C" = 200 ] && grep -q '"name": *"ContextGate"' /tmp/smoke_body.$$; then
  ok "1.1 根路径 name=ContextGate"
else
  bad "1.1 根路径 http=$C"
fi

# 1.2 健康检查(langfuse 报 configured 属正常,计 up 数)
C=$(code "$BASE/health")
HDB=$(grep -o '"status": *"up"' /tmp/smoke_body.$$ | wc -l | tr -d ' ')
if [ "$C" = 200 ] && [ "${HDB:-0}" -ge 4 ]; then
  ok "1.2 health 全绿($HDB 项 up)"
else
  bad "1.2 health 异常 http=$C up=$HDB"
fi

# 1.3 系统信息
C=$(code "$BASE/system/info")
if [ "$C" = 200 ] && grep -q '"chat"' /tmp/smoke_body.$$; then
  ok "1.3 system/info 含 chat/memory 等路由"
else
  bad "1.3 system/info http=$C"
fi

# 1.4 无 key 401
C=$(code -X POST "$BASE/chat" -H "Content-Type: application/json" -d '{"message":"hi"}')
if [ "$C" = 401 ] && grep -q "AUTH_001" /tmp/smoke_body.$$; then
  ok "1.4 无 key 401 AUTH_001"
else
  bad "1.4 无 key http=$C(应 401)"
fi

# 1.5 权限首查
C1=$(code "$BASE/api/admin/api-keys" -H "X-API-Key: $USER_KEY")
C2=$(code "$BASE/api/admin/api-keys" -H "X-API-Key: $SUPER_KEY")
if [ "$C1" = 403 ] && [ "$C2" = 200 ]; then
  ok "1.5 user=403 / super=200"
else
  bad "1.5 user=$C1 super=$C2(期望 403/200)"
fi

say ""
say "=== 结果: PASS=$PASS FAIL=$FAIL | 证据: $LOG ==="
rm -f /tmp/smoke_body.$$ 2>/dev/null
[ "$FAIL" = 0 ]
