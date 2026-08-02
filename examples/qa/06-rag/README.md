# QA — RAG 知识库 [T28 · T29]

> 来源: `docs/MANUAL_TEST.md` §6(6.1-6.17)。用例与一键脚本:
> **`../../scripts/rag_cache_qa.sh`**(缓存专项,覆盖 6.8-6.14/6.16)
> 页面: `http://localhost:8000/playground/rag.html`

## 用例速览

| # | 验证点 | 方式 |
|---|--------|------|
| 6.1 | init/sample [T28] | curl,chunks>0 且 embedding_model=text-embedding-v3 |
| 6.2 | upload/pdf [T28] | curl(必须真实 PDF;`.md` 伪装 pypdf 解析失败) |
| 6.3 | search 语义 [T28] | curl「信息安全管理制度」top-1 须为 COMPLIANCE 相关(硬验收) |
| 6.4 | ask 引用 [T28] | curl,回答有 sources |
| 6.5/6.6 | HyDE/ReRank 开关 [T20][T28] | 改 config.env 重启后对比 top-1,数据留档 |
| 6.7 | reset | curl,再 ask 走无知识路径 |
| 6.8-6.17 | 缓存/epoch/限流/PII/单飞/审计/降级/认证 [T29] | `scripts/rag_cache_qa.sh`(8 项全自动) |

## 一键

```bash
RAG_QA_KEY=<user key> ./scripts/rag_cache_qa.sh              # 6.8-6.14/6.16
RAG_QA_DEGRADE=1 RAG_QA_KEY=<key> ./scripts/rag_cache_qa.sh  # 含 redis 停启降级
```

## 手动(6.1-6.4)

```bash
KEY=<user key>; BASE=localhost:8000/api/rag
curl -s -X POST $BASE/init/sample -H "X-API-Key: $KEY" | python3 -m json.tool
# 真实 PDF: cupsfilter docs/COMPLIANCE.md > /tmp/c.pdf
curl -s -X POST $BASE/upload/pdf -H "X-API-Key: $KEY" -F "file=@/tmp/c.pdf" | python3 -m json.tool
curl -s "$BASE/search" -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"query":"信息安全管理制度","top_k":5}' | python3 -m json.tool
curl -s $BASE/ask -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"question":"如何查询公司的信息安全管理制度"}' | python3 -m json.tool
```
