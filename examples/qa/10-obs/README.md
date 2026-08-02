# QA — 可观测

> 来源: `docs/MANUAL_TEST.md` §10。混合形态: 页面清单 + 小脚本。
> 一键(脚本部分): `./examples/qa/10-obs/obs_qa.sh`

## 用例

| # | 验证点 | 操作 | 预期 |
|---|--------|------|------|
| 10.1 | LangFuse trace | 浏览器开 `http://localhost:3001`,发一条长路径 /chat | trace 名 `chat.pipeline` 出现,节点 span 全挂载;streaming 为 `chat.pipeline.streaming` |
| 10.2 | span 明细 | 点开 trace 的 `pipeline.llm_generate` | metadata 含 path/total_cost/total_tokens/ab_variant;usage 带 model/tokens(2026-08-02 修复);耗时精确到 ms(DB) |
| 10.3 | Prometheus | `curl localhost:8000/metrics/`(注意尾斜杠,否则 307) | 指标文本非空 |
| 10.4 | 缓存统计 | `GET /performance/cache/stats` | total_keys/memory_usage/hit_rate 合理 |
| 10.5 | 清缓存 | `POST /performance/cache/clear` | 计数归零 |
| 10.6 | RAG 缓存命中率 [T29] | `GET /api/rag/status` → `data.cache` | hit_ratio 随重复 query 上升 |
| 10.7 | redis 键检查 [T29] | `docker exec contextgate-redis-1 redis-cli --scan --pattern 'rag:*'` | L1/L2/epoch 键可见 |
| 10.8 | 滑动 TTL [T29] | 命中后 `redis-cli ttl <l1_key>` 复查 | TTL 回到 ~3600(≤4h 上限) |

> **LangFuse 详细用法(配合哪些 QA 看/指标含义/优化触发/error 排查): 见 [../LANGFUSE.md](../LANGFUSE.md)**

## 一键(10.3/10.4/10.6/10.7 自动;10.1/10.2/10.5/10.8 手动)

```bash
QA_KEY=<user key> ./examples/qa/10-obs/obs_qa.sh
```
