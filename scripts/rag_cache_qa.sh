#!/usr/bin/env bash
# RAG 缓存人工 QA 半自动脚本(Task 29)
#
# 用法:
#   RAG_QA_KEY=<user key> ./scripts/rag_cache_qa.sh
#   RAG_QA_KEY=<key> RAG_QA_BASE=localhost:8000 ./scripts/rag_cache_qa.sh
#   RAG_QA_DEGRADE=1 ./scripts/rag_cache_qa.sh   # 额外跑 redis 停启降级验证(会短暂停 redis)
#
# 覆盖: L1 20连发 / L2 复用 / 单飞锁 / PII 跳过 / epoch 失效 / miss 限流 429 / redis 键检查
# 输出: stdout + data/qa/rag_cache_qa_<ts>.log(证据留档)
# 注意: 压测步骤会消耗当分钟 miss 配额(10/min/租户),故放最后;跑完 1 分钟内正常 ask 可能被误限。
set -u

BASE="${RAG_QA_BASE:-localhost:8000}"
KEY="${RAG_QA_KEY:-}"
Q="${RAG_QA_Q:-如何查询公司的信息安全管理制度}"
PII_Q="${RAG_QA_PII:-我的身份证是110101199001011234请问制度如何查询}"
LOG="data/qa/rag_cache_qa_$(date +%Y%m%d_%H%M%S).log"
mkdir -p data/qa

if [ -z "$KEY" ]; then
  echo "缺少 RAG_QA_KEY(需要 user 角色以上的 key,可 make seed 或 admin 创建)" >&2
  exit 2
fi

PASS=0; FAIL=0
say()  { echo "$@" | tee -a "$LOG"; }
ok()   { PASS=$((PASS+1)); say "  ✅ $1"; }
bad()  { FAIL=$((FAIL+1)); say "  ❌ $1"; }

# $1=question -> 输出 "cache_hit|latency_ms";exit code 为 HTTP 状态
ask() {
  curl -s -o /tmp/rq_body.$$ -w "%{http_code}" -X POST "$BASE/api/rag/ask" \
    -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
    -d "{\"question\":\"$1\"}"
}
# $1=json文件 -> 提取 data 字段
dget() { python3 -c "import sys,json;print(json.load(open('$1')).get('data',{}).get('$2',''))" 2>/dev/null; }
# $1=json文件 -> 提取 error.code
eget() { python3 -c "import sys,json;print(json.load(open('$1')).get('error',{}).get('code',''))" 2>/dev/null; }

say "=== RAG 缓存 QA $(date '+%F %T') | base=$BASE ==="
say "问题: $Q"

# ── 0. 前置: 重置 + 初始化示例 + 上传真实 PDF(cupsfilter 生成)──
say ""
say "[0] 准备知识库(reset -> init/sample -> upload real pdf)"
GEN_PDF=/tmp/rag_qa_compliance.pdf
if command -v cupsfilter >/dev/null 2>&1; then
  cupsfilter docs/COMPLIANCE.md > "$GEN_PDF" 2>/dev/null || rm -f "$GEN_PDF"
fi
# 知识写入(上传真 PDF;cupsfilter 不可用时退回 init/sample,两者都会 bump epoch)
kb_write() {
  if [ -s "$GEN_PDF" ]; then
    curl -s -o /dev/null -X POST "$BASE/api/rag/upload/pdf" -H "X-API-Key: $KEY" -F "file=@$GEN_PDF"
  else
    curl -s -o /dev/null -X POST "$BASE/api/rag/init/sample" -H "X-API-Key: $KEY"
  fi
}
curl -s -o /dev/null -X DELETE "$BASE/api/rag/reset" -H "X-API-Key: $KEY"
curl -s -o /dev/null -X POST "$BASE/api/rag/init/sample" -H "X-API-Key: $KEY"
kb_write
curl -s -o /tmp/rq_status.$$ "$BASE/api/rag/status" -H "X-API-Key: $KEY"
EM=$(dget /tmp/rq_status.$$ embedding_model)
case "$EM" in
  *hash*) bad "embedding_model 为哈希兜底($EM),真实 embedding 未生效";;
  *)      ok "embedding_model=$EM(真实模型)";;
esac

# ── 1. L1: 同 query 20 连发 ──
say ""
say "[1] L1 缓存: 同 query 20 连发"
FIRST=""; LAT_SUM=0; LAT_N=0; MISS_N=0; HIT_N=0
for i in $(seq 1 20); do
  CODE=$(ask "$Q")
  CH=$(dget /tmp/rq_body.$$ cache_hit)
  LAT=$(dget /tmp/rq_body.$$ latency_ms)
  if [ "$i" = 1 ]; then FIRST="$CH"; fi
  if [ "$CH" = "False" ]; then MISS_N=$((MISS_N+1)); else HIT_N=$((HIT_N+1)); LAT_SUM=$(awk "BEGIN{print $LAT_SUM+$LAT}"); LAT_N=$((LAT_N+1)); fi
  printf "  #%02d http=%s cache_hit=%-5s latency=%sms\n" "$i" "$CODE" "$CH" "$LAT" | tee -a "$LOG"
done
if [ "$FIRST" = "False" ] && [ "$MISS_N" = 1 ] && [ "$HIT_N" = 19 ]; then
  AVG=$(awk "BEGIN{printf \"%.0f\", $LAT_SUM/$LAT_N}")
  say "  首次 miss,之后 19 次全 hit;命中平均延迟 ${AVG}ms"
  ok "L1: 1 miss + 19 hit"
else
  bad "L1 行为不符: first=$FIRST miss=$MISS_N hit=$HIT_N"
fi

# ── 2. L2: 同 query 3 次 search(应复用 embedding)──
say ""
say "[2] L2 缓存: 同 query 3 次 /search"
l2stat() { # $1=文件 -> 输出 "l2_hit,l2_entries"
  python3 -c "
import json
d = json.load(open('$1')).get('data', {}).get('cache', {})
print(d.get('l2_hit', 0), d.get('l2_entries', 0))
" 2>/dev/null
}
curl -s -o /tmp/rq_s0.$$ "$BASE/api/rag/status" -H "X-API-Key: $KEY"
read -r L2H0 L2E0 <<< "$(l2stat /tmp/rq_s0.$$)"
for i in 1 2 3; do
  curl -s -o /dev/null -X POST "$BASE/api/rag/search" -H "X-API-Key: $KEY" \
    -H "Content-Type: application/json" -d "{\"query\":\"$Q\",\"top_k\":3}" || true
done
sleep 1
curl -s -o /tmp/rq_s1.$$ "$BASE/api/rag/status" -H "X-API-Key: $KEY"
read -r L2H1 L2E1 <<< "$(l2stat /tmp/rq_s1.$$)"
L2H0=${L2H0:-0}; L2H1=${L2H1:-0}; L2E1=${L2E1:-0}
DELTA=$((L2H1 - L2H0))
if [ "$DELTA" -ge 2 ] && [ "$L2E1" -ge 1 ]; then
  ok "L2: l2_hit +$DELTA,l2_entries=$L2E1(embedding 已复用)"
else
  bad "L2 行为不符: l2_hit $L2H0->$L2H1,l2_entries=$L2E1"
fi

# ── 3. PII 跳过缓存 ──
say ""
say "[3] PII: 含身份证号的问题不落 L1"
N0=$(docker exec contextgate-redis-1 redis-cli --scan --pattern 'rag:a:*' 2>/dev/null | wc -l | tr -d ' ')
CODE=$(ask "$PII_Q")
CH=$(dget /tmp/rq_body.$$ cache_hit)
N1=$(docker exec contextgate-redis-1 redis-cli --scan --pattern 'rag:a:*' 2>/dev/null | wc -l | tr -d ' ')
if [ "$N1" = "$N0" ]; then
  ok "L1 键数不变($N0->$N1),PII 未落缓存"
else
  bad "PII 问题产生了 L1 键($N0->$N1)"
fi

# ── 4. 单飞锁: 5 并发同 query(新问题)-> 恰 1 个 miss ──
say ""
say "[4] 单飞锁: 5 并发同 query(新问题)"
CONC_Q="数据备份的恢复演练周期是多久"
rm -f /tmp/rq_conc_*.$$ 2>/dev/null
for i in 1 2 3 4 5; do
  ( curl -s -o /tmp/rq_conc_$i.$$ -X POST "$BASE/api/rag/ask" -H "X-API-Key: $KEY" \
      -H "Content-Type: application/json" -d "{\"question\":\"$CONC_Q\"}" >/dev/null 2>&1 ) &
done
wait
CF=0; CT=0
for i in 1 2 3 4 5; do
  if [ -s /tmp/rq_conc_$i.$$ ]; then
    CH=$(dget /tmp/rq_conc_$i.$$ cache_hit)
    [ "$CH" = "False" ] && CF=$((CF+1))
    [ "$CH" = "True" ] && CT=$((CT+1))
  fi
done
if [ "$CF" = 1 ] && [ "$CT" = 4 ]; then
  ok "单飞: 5 并发 -> 1 miss + 4 hit(仅 1 次 LLM 生成)"
else
  bad "单飞不符: false=$CF true=$CT(期望 1/4)"
fi

# ── 5. epoch 失效: 知识库写入后同 query 立即 miss ──
say ""
say "[5] epoch 失效: 知识写入(upload/init)后同 query 立即 cache_hit=false"
kb_write
CODE=$(ask "$Q")
CH=$(dget /tmp/rq_body.$$ cache_hit)
if [ "$CH" = "False" ]; then
  ok "upload 后同 query cache_hit=false(epoch 已翻转)"
else
  bad "epoch 失效未生效: cache_hit=$CH"
fi

# ── 6. miss 限流: 快速打 10 个不同 query -> 至少 1 个 429 RATE_001 ──
say ""
say "[6] 限流: 快速打 10 个不同 query(期望触发 RATE_001 429)"
RL_HIT=0
for i in 1 2 3 4 5 6 7 8 9 10; do
  CODE=$(ask "限流测试问题编号$i 关于信息安全")
  EC=$(eget /tmp/rq_body.$$)
  if [ "$CODE" = "429" ] && [ "$EC" = "RATE_001" ]; then RL_HIT=$((RL_HIT+1)); fi
done
if [ "$RL_HIT" -ge 1 ]; then
  ok "限流: 触发 $RL_HIT 次 429 RATE_001"
else
  bad "未触发限流(检查 RAG_RATE_LIMIT_MISS 与是否同分钟桶)"
fi

# ── 7. redis 键分布 ──
say ""
say "[7] redis 键分布(rag:* )"
if docker exec contextgate-redis-1 redis-cli --scan --pattern 'rag:*' 2>/dev/null | sort | head -20 | tee -a "$LOG" | grep -q .; then
  ok "redis 键可见(上方列表)"
else
  bad "redis 中无 rag:* 键"
fi

# ── 8. (可选)redis 降级 ──
if [ "${RAG_QA_DEGRADE:-0}" = "1" ]; then
  say ""
  say "[8] 降级: 停 redis -> ask 应照常(哈希/缓存穿透) -> 恢复"
  docker stop contextgate-redis-1 >/dev/null 2>&1
  sleep 1
  CODE=$(ask "降级测试问题")
  if [ "$CODE" = "200" ]; then ok "redis 停后 ask 仍 200(静默降级)"; else bad "redis 停后 ask http=$CODE"; fi
  docker start contextgate-redis-1 >/dev/null 2>&1
  sleep 2
  say "  redis 已恢复"
fi

# ── 汇总 ──
say ""
say "=== 结果: PASS=$PASS FAIL=$FAIL | 证据: $LOG ==="
rm -f /tmp/rq_*.$$ 2>/dev/null
[ "$FAIL" = 0 ]
