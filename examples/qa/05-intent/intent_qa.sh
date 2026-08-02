#!/usr/bin/env bash
# 意图识别 QA(MANUAL_TEST §5,5.1-5.5)
# 用法: QA_KEY=<user key> ./examples/qa/05-intent/intent_qa.sh
set -u

BASE="${QA_BASE:-localhost:8000}"
KEY="${QA_KEY:-${RAG_QA_KEY:-}}"
LOG="data/qa/intent_qa_$(date +%Y%m%d_%H%M%S).log"
mkdir -p data/qa

[ -z "$KEY" ] && echo "缺少 QA_KEY" >&2 && exit 2

PASS=0; FAIL=0
say() { echo "$@" | tee -a "$LOG"; }
ok()  { PASS=$((PASS+1)); say "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); say "  ❌ $1"; }
# $1=text -> 输出 "intent|confidence|http"
detect() {
  curl -s -o /tmp/it_body.$$ -w "%{http_code}" -X POST "$BASE/intent/detect" \
    -H "X-API-Key: $KEY" -G --data-urlencode "text=$1"
  python3 -c "
import sys,json
d=json.load(open('/tmp/it_body.$$'))
print(d.get('intent','') , d.get('confidence',''))
" 2>/dev/null
}

say "=== 意图识别 QA $(date '+%F %T') ==="

# 5.1 类型列表(应无情感域意图;advice/knowledge_query 属合法企业意图)
C=$(curl -s -o /tmp/it_body.$$ -w "%{http_code}" "$BASE/intent/types" -H "X-API-Key: $KEY")
if [ "$C" = 200 ] && ! grep -qE "emotion|情绪|倾诉|失眠" /tmp/it_body.$$; then
  ok "5.1 types 返回且无情感域意图"
else
  bad "5.1 types http=$C(检查情感意图残留)"
fi

# 5.2 企业问题命中
say "[5.2] 企业问题意图"
MISS=0
for q in "如何查询公司的信息安全管理制度" "报销流程是什么" "请假制度怎么规定" "设备报修找谁"; do
  OUT=$(detect "$q")
  IT=$(echo "$OUT" | awk '{print $1}'); CONF=$(echo "$OUT" | awk '{print $2}')
  printf "  %-20s -> intent=%s conf=%s\n" "$q" "$IT" "$CONF" | tee -a "$LOG"
  if [ "$IT" = "advice" ]; then MISS=$((MISS+1)); fi
done
if [ "$MISS" = 0 ]; then
  ok "5.2/5.3 企业问题全部命中合理意图,无 advice 兜底"
else
  bad "5.2/5.3 有 $MISS 条兜进 advice"
fi

# 5.4 analyze 全量
C=$(curl -s -o /tmp/it_body.$$ -w "%{http_code}" -X POST "$BASE/intent/analyze" \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"text":"如何查询公司的信息安全管理制度"}')
if [ "$C" = 200 ] && grep -q "confidence" /tmp/it_body.$$; then
  ok "5.4 analyze 返回意图+置信度"
else
  bad "5.4 analyze http=$C"
fi

# 5.5 文案残留
if grep -rn "睡不着\|失眠\|难过" backend/ --include="*.py" 2>/dev/null | grep -v __pycache__ | grep -q .; then
  bad "5.5 情感文案残留(见上方 grep)"
else
  ok "5.5 情感文案 0 残留"
fi

say ""
say "=== 结果: PASS=$PASS FAIL=$FAIL | 证据: $LOG ==="
rm -f /tmp/it_body.$$ 2>/dev/null
[ "$FAIL" = 0 ]
