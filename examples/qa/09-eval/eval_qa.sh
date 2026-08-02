#!/usr/bin/env bash
# 评测 QA(MANUAL_TEST §9,9.1-9.4)
# 用法: QA_KEY=<user key> ./examples/qa/09-eval/eval_qa.sh
set -u

BASE="${QA_BASE:-localhost:8000}"
KEY="${QA_KEY:-${RAG_QA_KEY:-}}"
LOG="data/qa/eval_qa_$(date +%Y%m%d_%H%M%S).log"
mkdir -p data/qa

[ -z "$KEY" ] && echo "缺少 QA_KEY" >&2 && exit 2

PASS=0; FAIL=0
say() { echo "$@" | tee -a "$LOG"; }
ok()  { PASS=$((PASS+1)); say "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); say "  ❌ $1"; }
code() { curl -s -o /tmp/ev_body.$$ -w "%{http_code}" -H "X-API-Key: $KEY" "$@"; }

say "=== 评测 QA $(date '+%F %T') ==="

# 9.1 单条评测
C=$(code -X POST "$BASE/evaluation/evaluate" -H "Content-Type: application/json" \
  -d '{"user_message":"如何查询公司制度","bot_response":"请查看信息安全管理制度文件"}')
if [ "$C" = 200 ] && grep -q "accuracy_score" /tmp/ev_body.$$; then
  ok "9.1 evaluate 返回评分"
else
  bad "9.1 evaluate http=$C"
fi

# 9.2 批量
C=$(code -X POST "$BASE/evaluation/batch" -H "Content-Type: application/json" -d '{"limit":3}')
if [ "$C" = 200 ]; then
  ok "9.2 batch 200"
else
  bad "9.2 batch http=$C"
fi

# 9.3 对比
C=$(code -X POST "$BASE/evaluation/compare-prompts" -H "Content-Type: application/json" \
  -d '{"user_message":"如何查询制度","responses":{"v1":"看制度文件","v2":"请参考信息安全管理制度"}}')
if [ "$C" = 200 ]; then
  ok "9.3 compare-prompts 200"
else
  bad "9.3 compare http=$C"
fi

# 9.4 统计
C=$(code "$BASE/evaluation/statistics")
if [ "$C" = 200 ] && grep -qE "total_count|average" /tmp/ev_body.$$; then
  ok "9.4 statistics 聚合正常"
else
  bad "9.4 statistics http=$C"
fi

say ""
say "=== 结果: PASS=$PASS FAIL=$FAIL | 证据: $LOG ==="
rm -f /tmp/ev_body.$$ 2>/dev/null
[ "$FAIL" = 0 ]
