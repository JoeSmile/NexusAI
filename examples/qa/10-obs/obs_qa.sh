#!/usr/bin/env bash
# 可观测 QA(自动部分: /metrics /performance/cache/stats /api/rag/status cache / redis 键)
# 用法: QA_KEY=<user key> ./examples/qa/10-obs/obs_qa.sh
set -u

BASE="${QA_BASE:-localhost:8000}"
KEY="${QA_KEY:-${RAG_QA_KEY:-}}"
REDIS="${QA_REDIS:-contextgate-redis-1}"
LOG="data/qa/obs_qa_$(date +%Y%m%d_%H%M%S).log"
mkdir -p data/qa

[ -z "$KEY" ] && echo "缺少 QA_KEY" >&2 && exit 2

PASS=0; FAIL=0
say() { echo "$@" | tee -a "$LOG"; }
ok()  { PASS=$((PASS+1)); say "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); say "  ❌ $1"; }

say "=== 可观测 QA $(date '+%F %T') ==="

# 10.3 Prometheus(/metrics 307 -> /metrics/)
C=$(curl -sL -o /tmp/obs_body.$$ -w "%{http_code}" "$BASE/metrics")
if [ "$C" = 200 ] && grep -q "contextgate_cache_hits_total" /tmp/obs_body.$$; then
  ok "10.3 /metrics/ 指标含缓存计数器"
else
  bad "10.3 /metrics http=$C"
fi

# 10.4 缓存统计
C=$(curl -s -o /tmp/obs_body.$$ -w "%{http_code}" "$BASE/performance/cache/stats" -H "X-API-Key: $KEY")
if [ "$C" = 200 ] && grep -q "hit_rate" /tmp/obs_body.$$; then
  ok "10.4 cache/stats 含 hit_rate"
else
  bad "10.4 cache/stats http=$C"
fi

# 10.6 RAG 缓存命中率
C=$(curl -s -o /tmp/obs_body.$$ -w "%{http_code}" "$BASE/api/rag/status" -H "X-API-Key: $KEY")
if [ "$C" = 200 ] && grep -q '"cache"' /tmp/obs_body.$$; then
  HR=$(python3 -c "import json;print(json.load(open('/tmp/obs_body.$$')).get('data',{}).get('cache',{}).get('hit_ratio','?'))" 2>/dev/null)
  ok "10.6 rag/status.cache hit_ratio=$HR"
else
  bad "10.6 rag/status http=$C(缺 cache 字段)"
fi

# 10.7 redis 键分布
if docker exec "$REDIS" redis-cli --scan --pattern 'rag:*' 2>/dev/null | grep -q .; then
  N=$(docker exec "$REDIS" redis-cli --scan --pattern 'rag:*' 2>/dev/null | wc -l | tr -d ' ')
  ok "10.7 redis rag:* 键 $N 个"
else
  bad "10.7 redis rag:* 无键(容器 $REDIS 不在?缓存未启用?)"
fi

say ""
say "=== 结果: PASS=$PASS FAIL=$FAIL | 证据: $LOG ==="
rm -f /tmp/obs_body.$$ 2>/dev/null
[ "$FAIL" = 0 ]
