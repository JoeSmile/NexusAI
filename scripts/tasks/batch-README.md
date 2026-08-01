# ContextGate — Cursor 执行批次索引

> 18 个 Task · 79 个 Subtask → 8 个 Cursor 可执行的 Batches (+ 独立 Task 19)

## 执行顺序

```bash
Batch 1  →  Batch 2  →  Batch 3  →  Batch 4  →  Batch 5a + 5b (可并行)  →  Batch 6  →  Batch 7  →  Batch 8
基建         安全骨架     租户+健康     核心管线      平行能力                锁依赖      部署           收尾
```

## 批次文件

| Batch | 文件 | Tasks | Subtasks | 预估 |
|-------|------|-------|----------|------|
| 1 | `tasks/batch-01-rebranding-pgvector.md` | 00+01 | 10 | 40-60min |
| 2 | `tasks/batch-02-auth-rbac-signature.md` | 02 | 6 | 30-50min |
| 3 | `tasks/batch-03-tenant-audit-health.md` | 03+12 | 7 | 20-35min |
| 4 | `tasks/batch-04-langgraph-pipeline.md` | 04 | 11（含延期 SSE 04.11） | **60-90min** ⚠️ 最大 |
| 5a | `tasks/batch-05a-observability-cache-guardrails.md` | 05+06+09+10+11 | 15（含流式 abort 09.04） | 40-60min |
| 5b | `tasks/batch-05b-cost-router-skill-harness.md` | 07 | 7+（含 stream 07.07e） | 50-70min |
| 6 | `tasks/batch-06-deps-seed-mock.md` | 08+13 | 4 | 15-25min |
| 7 | `tasks/batch-07-docker-cicd-production.md` | 14+15+16 | 9 | 25-35min |
| 8 | `tasks/batch-08-ownership-key-governance.md` | 17+18 | 14 | 50-70min |
| — | `tasks/19-enhance-bottleneck.md` | 19 | 10 | 待定 — 建议拆成 2 个子批次执行 |

## 重点警告

**P0 — 架构级（Cursor 最容易翻车的）：**

1. **PipelineState 是 TypedDict 不是 Pydantic** — 每个节点用 `state["key"]` 而不是 `state.key`
2. **Harness 重构会波及多个节点** — Batch 5b 必须在一个 Cursor 对话中完成
3. **`request.body()` 消费流** — Batch 2 的签名中间件必须缓存 body
4. **`config.LLM_API_KEY` 全局替换** — Batch 8 要逐个搜索替换，保留 fallback

**P1 — 性能瓶颈（Task 19 特别警告）：**

5. **`database.py` 模块级 pymysql 探测** — Task 19.01 之前不要并行引入需要 `from backend.database import ...` 的新模块，会触发 3s 阻塞
6. **`VectorStore.__init__` ONNX 下载** — Task 19.02 之前第一个向量操作会卡 5-30s，CI 需跳过
7. **`config.py` 模块级 static eval** — Task 19.03 之前注水基准线，测完了再改
8. **不做 Task 19 直接做 Batch 4 (LangGraph) 的后果：** 新 pipeline 的性能基线会被现有瓶颈污染，无法判断是 LangGraph 慢还是系统慢

**P2 — 依赖顺序：**

9. Batch 5b 依赖 Batch 2+3+4 — 不要并行
10. Batch 8 依赖 Batch 5b 的 model_router — Batch 8 最后做

## 执行建议

- 每个 Batch 一个 commit
- Batch 4 和 Batch 5b 必须在**同一个 Cursor 对话**中完成
- 每做完一个 Batch 跑一次验证命令
- Batch 6 做 `uv lock && uv sync` 确保所有依赖就绪
