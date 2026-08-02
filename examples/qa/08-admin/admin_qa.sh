#!/usr/bin/env bash
# Admin 管理 QA(MANUAL_TEST §8,8.1-8.6)
# 用法: QA_USER_KEY=<user> QA_SUPER_KEY=<super_admin> ./examples/qa/08-admin/admin_qa.sh
set -u

BASE="${QA_BASE:-localhost:8000}"
SUPER="${QA_SUPER_KEY:-}"
USER="${QA_USER_KEY:-${RAG_QA_KEY:-}}"
LOG="data/qa/admin_qa_$(date +%Y%m%d_%H%M%S).log"
mkdir -p data/qa

[ -z "$SUPER" ] && echo "缺少 QA_SUPER_KEY" >&2 && exit 2

PASS=0; FAIL=0
say() { echo "$@" | tee -a "$LOG"; }
ok()  { PASS=$((PASS+1)); say "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); say "  ❌ $1"; }
sup()  { curl -s -o /tmp/ad_body.$$ -w "%{http_code}" -H "X-API-Key: $SUPER" "$@"; }
usr()  { curl -s -o /tmp/ad_body.$$ -w "%{http_code}" -H "X-API-Key: $USER" "$@"; }

say "=== Admin QA $(date '+%F %T') ==="

# 8.1 创建 api-key(唯一 user_id,可重复跑)
RID="qa_$(date +%H%M%S)"
C=$(sup -X POST "$BASE/api/admin/api-keys" -H "Content-Type: application/json" \
  -d "{\"user_id\":\"$RID\",\"role\":\"user\",\"tenant_id\":\"default\",\"description\":\"admin QA\"}")
NEW_KEY=$(python3 -c "import json;print(json.load(open('/tmp/ad_body.$$')).get('api_key',''))" 2>/dev/null)
KID=$(python3 -c "import json;print(json.load(open('/tmp/ad_body.$$')).get('key',{}).get('id',''))" 2>/dev/null)
if [ "$C" = 200 ] && [ -n "$NEW_KEY" ]; then
  ok "8.1 创建 key $RID (id=$KID)"
else
  bad "8.1 创建 key http=$C"
fi

# 8.2 删除后原 key 401
if [ -n "$KID" ]; then
  C=$(sup -X DELETE "$BASE/api/admin/api-keys/$KID")
  C2=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/chat" -H "X-API-Key: $NEW_KEY" -H "Content-Type: application/json" -d '{"message":"hi"}')
  if [ "$C" = 200 ] && [ "$C2" = 401 ]; then
    ok "8.2 删除后 key 请求 401"
  else
    bad "8.2 删除 http=$C 删除后请求=$C2(应 401)"
  fi
fi

# 8.3 llm-keys 加密入库 + 列表不显示明文
C=$(sup -X POST "$BASE/api/admin/llm-keys" -H "Content-Type: application/json" \
  -d "{\"key_alias\":\"qa-test-$RID\",\"api_key_plaintext\":\"sk-qa-plaintext-$RID\"}")
LKID=$(python3 -c "import json;print(json.load(open('/tmp/ad_body.$$')).get('id',''))" 2>/dev/null)
C2=$(sup "$BASE/api/admin/llm-keys")
if [ "$C" = 200 ] && [ -n "$LKID" ] && ! grep -q "sk-qa-plaintext-$RID" /tmp/ad_body.$$; then
  ok "8.3 llm-key 加密入库,列表无明文(id=$LKID)"
else
  bad "8.3 llm-keys http=$C(明文泄露或创建失败)"
fi

# 8.4 llm-keys verify
if [ -n "${LKID:-}" ]; then
  C=$(sup -X POST "$BASE/api/admin/llm-keys/$LKID/verify")
  if [ "$C" = 200 ]; then
    ok "8.4 verify 返回连通性结果"
  else
    bad "8.4 verify http=$C"
  fi
fi

# 8.5 审批流(user 请求权限 → admin 看到 pending → approve)
if [ -n "$USER" ]; then
  C=$(usr -X POST "$BASE/api/admin/permissions/request" -H "Content-Type: application/json" \
    -d "{\"resource\":\"qa:test:$RID\",\"reason\":\"QA 审批流验证\"}")
  C2=$(sup "$BASE/api/admin/pending-requests")
  REQID=$(python3 -c "
import json
d=json.load(open('/tmp/ad_body.$$'))
if isinstance(d,list):
    hit=[r for r in d if r.get('resource')=='qa:test:$RID']
    print(hit[0].get('id','') if hit else '')
else:
    print('')
" 2>/dev/null)
  if [ "$C" = 200 ] && [ "$C2" = 200 ] && [ -n "$REQID" ]; then
    C3=$(sup -X POST "$BASE/api/admin/approve" -H "Content-Type: application/json" \
      -d "{\"request_id\":$REQID,\"approved\":true,\"reason\":\"QA approve\"}")
    [ "$C3" = 200 ] && ok "8.5 审批流 request->pending->approved(id=$REQID)" \
                   || bad "8.5 approve http=$C3"
  else
    bad "8.5 审批流 http=$C/$C2(或无 pending 请求)"
  fi
fi

# 8.6 audit 导出
C=$(sup "$BASE/api/audit/export")
if [ "$C" = 200 ] && [ -s /tmp/ad_body.$$ ]; then
  ok "8.6 audit 导出 $C($(wc -c < /tmp/ad_body.$$) bytes)"
else
  bad "8.6 audit 导出 http=$C"
fi

say ""
say "=== 结果: PASS=$PASS FAIL=$FAIL | 证据: $LOG ==="
rm -f /tmp/ad_body.$$ 2>/dev/null
[ "$FAIL" = 0 ]
