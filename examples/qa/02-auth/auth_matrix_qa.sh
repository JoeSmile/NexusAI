#!/usr/bin/env bash
# 认证权限矩阵 QA(MANUAL_TEST §2;5 端点 x 4 角色)
# 用法: 4 个角色 key 通过 env 传入(缺哪个角色,该角色列跳过)
#   QA_USER_KEY QA_TADMIN_KEY QA_AUDITOR_KEY QA_SUPER_KEY ./examples/qa/02-auth/auth_matrix_qa.sh
set -u

BASE="${QA_BASE:-localhost:8000}"
LOG="data/qa/auth_matrix_qa_$(date +%Y%m%d_%H%M%S).log"
mkdir -p data/qa

PASS=0; FAIL=0; SKIP=0
say() { echo "$@" | tee -a "$LOG"; }
ok()  { PASS=$((PASS+1)); say "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); say "  ❌ $1"; }
skip(){ SKIP=$((SKIP+1)); say "  ⏭  $1(未提供 key)"; }

# $1=key $2=描述 $3=期望状态(逗号分隔允许值) $4+=curl 参数
expect() {
  local key="$1" desc="$2" want="$3"; shift 3
  if [ -z "$key" ]; then skip "$desc"; return; fi
  local c
  c=$(curl -s -o /tmp/am_body.$$ -w "%{http_code}" -H "X-API-Key: $key" "$@")
  local matched=0
  for w in ${want//,/ }; do [ "$c" = "$w" ] && matched=1; done
  if [ "$matched" = 1 ]; then ok "$desc=$c"; else bad "$desc=$c(期望 $want)"; fi
}

say "=== 认证权限矩阵 QA $(date '+%F %T') ==="

# 1. POST /chat (chat:write)  — user/tadmin/super 200;auditor 403
expect "${QA_USER_KEY:-}"    "chat  user        " "200" -X POST "$BASE/chat" -H "Content-Type: application/json" -d '{"message":"你好"}'
expect "${QA_TADMIN_KEY:-}"  "chat  tenant_admin" "200" -X POST "$BASE/chat" -H "Content-Type: application/json" -d '{"message":"你好"}'
expect "${QA_AUDITOR_KEY:-}" "chat  auditor     " "403" -X POST "$BASE/chat" -H "Content-Type: application/json" -d '{"message":"你好"}'
expect "${QA_SUPER_KEY:-}"   "chat  super_admin " "200" -X POST "$BASE/chat" -H "Content-Type: application/json" -d '{"message":"你好"}'

# 2. GET /api/admin/api-keys (admin:*) — 仅 super 200
expect "${QA_USER_KEY:-}"    "keys  user        " "403" "$BASE/api/admin/api-keys"
expect "${QA_TADMIN_KEY:-}"  "keys  tenant_admin" "403" "$BASE/api/admin/api-keys"
expect "${QA_AUDITOR_KEY:-}" "keys  auditor     " "403" "$BASE/api/admin/api-keys"
expect "${QA_SUPER_KEY:-}"   "keys  super_admin " "200" "$BASE/api/admin/api-keys"

# 3. POST /api/admin/approve (admin:approve) — tadmin/super 非403(无 request_id 时 4xx 也说明过了权限关)
expect "${QA_USER_KEY:-}"    "approve user        " "403" -X POST "$BASE/api/admin/approve" -H "Content-Type: application/json" -d '{"request_id":999999,"approved":true}'
expect "${QA_TADMIN_KEY:-}"  "approve tenant_admin" "400,404,200,422" -X POST "$BASE/api/admin/approve" -H "Content-Type: application/json" -d '{"request_id":999999,"approved":true}'
expect "${QA_AUDITOR_KEY:-}" "approve auditor     " "403" -X POST "$BASE/api/admin/approve" -H "Content-Type: application/json" -d '{"request_id":999999,"approved":true}'
expect "${QA_SUPER_KEY:-}"   "approve super_admin " "400,404,200,422" -X POST "$BASE/api/admin/approve" -H "Content-Type: application/json" -d '{"request_id":999999,"approved":true}'

# 4. GET /api/audit/logs (audit:read) — auditor/super 200
expect "${QA_USER_KEY:-}"    "audit  user        " "403" "$BASE/api/audit/logs?limit=1"
expect "${QA_TADMIN_KEY:-}"  "audit  tenant_admin" "403" "$BASE/api/audit/logs?limit=1"
expect "${QA_AUDITOR_KEY:-}" "audit  auditor     " "200" "$BASE/api/audit/logs?limit=1"
expect "${QA_SUPER_KEY:-}"   "audit  super_admin " "200" "$BASE/api/audit/logs?limit=1"

# 5. GET /api/audit/export (audit:export) — auditor/super 200
expect "${QA_USER_KEY:-}"    "export user        " "403" "$BASE/api/audit/export"
expect "${QA_TADMIN_KEY:-}"  "export tenant_admin" "403" "$BASE/api/audit/export"
expect "${QA_AUDITOR_KEY:-}" "export auditor     " "200" "$BASE/api/audit/export"
expect "${QA_SUPER_KEY:-}"   "export super_admin " "200" "$BASE/api/audit/export"

say ""
say "=== 结果: PASS=$PASS FAIL=$FAIL SKIP=$SKIP | 证据: $LOG ==="
rm -f /tmp/am_body.$$ 2>/dev/null
[ "$FAIL" = 0 ]
