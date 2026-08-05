# 12o — 可观测：LangFuse · Prometheus · 审计（含怎么看指标）

> 面试目标：说清「三本账」；按 `trace_id` / 目标态 `run_id` 定位。  
> 锚点：`observability/*` · `core/metrics.py` · `pipeline/router.py` · `/metrics`  
> 实测：[`examples/qa/LANGFUSE.md`](../examples/qa/LANGFUSE.md)  
> 串讲：接在运行时分流与 Runner 之后——「可认证、可分流、可计量、可回放、可审计」。

---

## 0. 三本账（别混）

| 账本 | 回答的问题 | 入口 |
|------|------------|------|
| **LangFuse** | 这一次请求走过哪些节点？耗时/用量/成本？短还是长路径？ | UI `http://localhost:3001` |
| **Prometheus** | 租户级聚合：QPS、命中、拦截、累计 cost/token、错误码 | `curl :8000/metrics`（或 Grafana） |
| **audit_logs** | 合规溯源：谁、何时、输入输出摘要、error_code | Audit 面板 / SQL（auditor） |

**一句话：**  
LangFuse = 单次手术录像；Prometheus = 病房仪表盘；Audit = 病历归档。

```text
请求 ──@observe / enrich_span──► LangFuse（可采样 discard）
     ──Counter/Histogram──────► /metrics → Prometheus scrape
     ──log_audit / write_*────► audit_logs（及 RAG rag.ask）
```

---

## 1) LangFuse — 怎么看（面试 + 实操）

### 1.1 启动与登录

```bash
# 常见：compose 已起 langfuse，宿主机映射 3001
open http://localhost:3001
# 本地 init 账号见 config.env.example（如 admin@contextgate.local）
# 需 LANGFUSE_PUBLIC_KEY / SECRET_KEY / HOST；LANGFUSE_ENABLED 可关
```

Chat 响应体里的 **`trace_id`** 是第一检索键（采样丢掉时以日志为准）。

### 1.2 一次长路径该长什么样

1. Chat 发一句会走 LLM 的话（非「你好」skill）  
2. LangFuse → Traces → 搜 `chat.pipeline` 或 `trace_id`  
3. 打开后应看到：

| 层级 | 名称（例） | 看什么 |
|------|------------|--------|
| Trace | `chat.pipeline` / `chat.pipeline.streaming` | 整次请求 |
| SPAN | `pipeline.auth_check` … `pipeline.write_memory` | 节点有无、顺序、耗时 |
| GENERATION | `pipeline.llm_generate` | model、prompt/completion tokens、输出 |

**最可信的业务标签（metadata）：**

| 字段 | 含义 |
|------|------|
| `path` | `long` / `short`（比猜 finish_reason 稳） |
| `total_cost` / `total_tokens` | 与 API 响应对齐的成本/用量（优先看 metadata，勿只信 UI cost 列） |
| `ab_variant` / `ab_experiment_id` | A/B |
| generation `usage` | input/output tokens（须走 `update_current_observation`，已修 GAP-08） |

### 1.3 采样（为什么有时「明明打了却没有 trace」）

| 路径 | 默认采样 | 环境变量 |
|------|----------|----------|
| 长路径（LLM） | **100%** | `LANGFUSE_SAMPLE_LONG_PATH=1.0` |
| 短路径（skill / cache_hit / blocked / rate_limited …） | **10%** | `LANGFUSE_SAMPLE_SHORT_PATH=0.1` |

实现：`observability/sampling.py`；短路径未命中采样时 router `finally` → `discard_langfuse_buffer`，命中 → `flush_langfuse`。

演示时若要稳定看到 greeting/cache：临时把 short 采样调到 `1.0`。

### 1.4 嵌套如何保证（GAP-08）

LangGraph 会丢 contextvar → `_lf_node` 把 `_lf_trace_id` / `_lf_parent_obs_id` 塞进 state，节点 span 挂回根 trace。  
UI 里 parentObservationId 为空、呈平铺列表可以是正常语义，看 start/end 耗时即可。

### 1.5 Public API 读数注意

- 字段 **camelCase**（`startTime` / `endTime`）  
- observations 的 `latency` 字段可能显示 0 → 用 UI 或直查 langfuse DB：

```bash
docker exec contextgate-postgres-1 psql -U contextgate -d langfuse -c \
  "SELECT name, start_time, end_time, (end_time-start_time) AS dur
   FROM observations WHERE trace_id='<id>';"
```

```bash
curl -u "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" \
  "$LANGFUSE_HOST/api/public/traces?limit=5"
```

### 1.6 从 LangFuse 判断「该优化什么」

| 现象 | 解读 | 动作 |
|------|------|------|
| `path=long` 过多 | skill/缓存没接住 | 查 intent 置信度、skill、cache key |
| `total_cost` / tokens 暴涨 | 上下文膨胀或贵模型 | 查 build_context、model_registry tier |
| blocked 频繁 | 误伤或攻击 | 看 guardrails_input 的 input |
| 找不到 trace | 短路径被采样 / 没走 chat | 调采样或查日志 |
| 无 llm_generate | short 或 cache | 预期行为 |

### 1.7 诚实边界

- **RAG / Agent / Eval** 多数未挂 `@observe` → 默认不进 LangFuse（见 LANGFUSE.md）  
- generation UI「成本列」依赖 LangFuse 模型价目表；**以 metadata.total_cost 为准**  
- 错误排查优先：响应 `error_code` + 日志 + trace，不只靠 UI 红标

---

## 2) Prometheus — 指标字典与怎么读

### 2.1 暴露方式

```bash
# 进程内挂载（app.py）
curl -s http://localhost:8000/metrics | head
# scrape：monitoring/prometheus.yml → job contextgate → :8000/metrics
```

中间件 `MetricsMiddleware`：每个 HTTP 请求记 latency + `requests_total`（租户来自 `request.state.tenant_context`）。

### 2.2 核心指标（背名称 + label）

| 指标 | 类型 | Labels | 谁在 incr |
|------|------|--------|-----------|
| `contextgate_request_duration_ms` | Histogram | method, endpoint, status | Middleware；Harness.wrap 也 observe |
| `contextgate_requests_total` | Counter | tenant, status | Middleware |
| `contextgate_tokens_total` | Counter | tenant, model | `record_consumption`（Harness） |
| `contextgate_cost_total` | Counter | tenant, model | 同上 |
| `contextgate_cache_hits_total` | Counter | tenant, cache_type | `cache_check`（exact/template） |
| `contextgate_cache_misses_total` | Counter | tenant, cache_type | cache miss |
| `contextgate_guardrails_blocked_total` | Counter | tenant, guard | injection/pii 等 |
| `contextgate_errors_total` | Counter | tenant, error_code | Harness 超时等 |

### 2.3 现场怎么「读」

```bash
# 1) 命中率粗算（按租户过滤可 grep）
curl -s localhost:8000/metrics | grep contextgate_cache_

# 2) 成本/token 是否在涨（打几轮 long path 后再 curl）
curl -s localhost:8000/metrics | grep -E 'contextgate_(cost|tokens)_total'

# 3) 护栏是否误伤
curl -s localhost:8000/metrics | grep guardrails_blocked

# 4) 延迟分布（histogram bucket + _sum/_count）
curl -s localhost:8000/metrics | grep request_duration_ms
```

**PromQL 示例（有 Prometheus UI :9090 时）：**

```promql
# 请求速率
sum(rate(contextgate_requests_total[5m])) by (tenant, status)

# 缓存命中率（需 hits+misses 都有）
sum(rate(contextgate_cache_hits_total[5m]))
/
(sum(rate(contextgate_cache_hits_total[5m])) + sum(rate(contextgate_cache_misses_total[5m])))

# 租户成本增速
sum(rate(contextgate_cost_total[5m])) by (tenant, model)
```

### 2.4 与 FE Performance 面板

测试 FE「性能」卡：`/performance/metrics`、cache stats、streams、benchmark（需 `chat:write`；清缓存另要 admin）。  
这是**产品化摘要**，底层仍可能混有 optimizer 统计；面试说「面板看趋势，对账以 /metrics + LangFuse metadata 为准」。

### 2.5 诚实边界

- Counter **只增不减**；重启进程归零——看 rate 不看裸瞬时值做长期报表  
- Chat exact 命中差时，`cache_hits` 可能长期接近 0（对应 Task 39）  
- RAG L1/L2 另有 status/redis 统计，**不完全**等同 `contextgate_cache_*`（管线 exact/template）

---

## 3) 审计 — 合规怎么查

| 来源 | action 例 | 看什么 |
|------|-----------|--------|
| Chat router `log_audit` | `chat` | input/output 摘要、model、cost、latency、error_code、trace_id |
| `write_memory` 内 SQL | （实现侧） | 与 router 可能双通道——开口说「以 audit 表 + trace_id 交叉」 |
| RAG | `rag.ask` | input 前缀 `cache_hit=0\|` / `1\|` + 归一化问句 |
| Auth | `auth.login` / `auth.register` | 账号事件 |
| Capability | `capability.invoke` | Hub 调用 |

**操作：** 切 **auditor**（或 super_admin）→ Audit 面板按 action/时间过滤；导出 CSV。  
**面试：** 「观测解决工程定位；审计解决合规举证——角色上 auditor 跨租户只读。」

### 3.1 目标态审计字段（Runner / 凭证拆分后）

| 字段 | 用途 |
|------|------|
| `run_id` / `node_id` | Workflow 运行与挂起续跑 |
| `acting_user_id` | 谁点的（人） |
| `credential_kind` | human_session / machine_key / delegation |
| `org` / 主部门 | OrgScope 举证 |
| `connector_key_id` | 出站用了哪把连接器密钥（不含明文） |

金线：跑链 → 挂起批过 → auditor 导出能看见上表。设计见 pilot-b §9/§10/§12。

---

## 4) 端到端排查剧本（30 秒定位）

```text
1. 复现请求，记下：HTTP 状态、finish_reason / error_code、trace_id、total_cost
2. 有 trace_id → LangFuse 打开
      · 有无 llm_generate？→ 长/短
      · 哪一节 span 特别长？→ 性能
      · metadata.path / tokens / cost
3. 无 trace → 是否短路径采样？调 SAMPLE 或看 uvicorn 日志
4. 聚合异常（某租户突然贵）→ /metrics 看 cost_total{tenant=…} rate
5. 合规要证据 → Audit 按 trace_id / 时间捞行
```

---

## 5) 代码埋点地图（面试指文件）

| 机制 | 文件 |
|------|------|
| `@observe` / `enrich_span` / 采样门控 | `observability/decorators.py` |
| 采样率 | `observability/sampling.py` + settings |
| 客户端 flush/discard | `observability/langfuse_client.py` |
| 根 trace + 收尾 flush | `pipeline/router.py`（`_run_chat_pipeline`） |
| 节点挂父 span | `pipeline/graph.py` `_lf_node` |
| usage 上报 | `harness/llm.py` → `update_current_observation` |
| Prometheus 定义 + 中间件 | `core/metrics.py` |
| 挂载 | `app.py` → `/metrics` |

---

## 6) 三维速记

### 图
- Chat 主链 observe 密；RAG/Agent 观测覆盖弱 → 诚实缺口  
- metrics 热点与 harness/cache/guard 写入点一致  

### 面试官

1. 三本账各解决什么？→ 单次 / 聚合 / 合规  
2. 为什么 greeting 常常没有 trace？→ 短路径 10% 采样  
3. cost 看 UI 还是 metadata？→ metadata.total_cost  
4. Prometheus 命中率怎么算？→ hits/(hits+misses) rate  
5. GAP-08 修了啥？→ usage API 方法名 + streaming 根 observe  

### 求职者 60 秒

> 我们用 LangFuse 做请求级 span 树，长路径全量、短路径降采样控成本；Prometheus 暴露租户维度的 QPS、缓存、护栏、token 与成本；审计表给合规角色做溯源。  
> 出问题先拿 trace_id 看节点和 path，再用 /metrics 看是否系统性变贵或被拦，最后用 audit 留证。

---

## 7) 还能怎么更好

| 优先级 | 点 |
|--------|----|
| P0 | RAG/Agent 补 `@observe`，与 chat 同一套检索习惯 |
| P1 | Grafana 看板预置：命中率、cost by tenant、guard rate、p95 latency |
| P1 | 错误 span level=ERROR 与 AUTH_/COST_ 对齐，减少「UI 全绿但业务失败」 |
| P2 | 审计与 LangFuse trace_id 强制同源字段，面板一键跳转 |

---

## 8) 自测清单

- [ ] 长路径：LangFuse 有 `llm_generate` + usage  
- [ ] 短路径：默认可能无 trace；调 `LANGFUSE_SAMPLE_SHORT_PATH=1` 后可见  
- [ ] `curl /metrics` 能指出至少 4 个 `contextgate_*` 名  
- [ ] auditor 能在 Audit 看到对应 `chat` / `rag.ask`  
- [ ] 能口述「找不到 trace」的两种原因（采样 / 非 chat 入口）

```bash
# 快速冒烟
curl -s -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"message":"用三句话解释向量检索","session_id":"obs-1"}' \
  http://localhost:8000/chat | jq '{trace_id,finish_reason,total_cost}'
curl -s localhost:8000/metrics | grep -E 'contextgate_(cache|cost|tokens|guardrails)_' | head
open http://localhost:3001
```

---

## 9) 衔接

- 总图 [00](00-interview-map.md) · 分流 [02](02-runtime-split.md) · Runner [06](06-workflow-runner.md)  
- 认证 [04a](04a-auth-rbac.md) · Chat [05b](05b-pipeline-nodes.md) · Hub [09d](09d-rag-capability.md)  
- 细节与已知坑：[`examples/qa/LANGFUSE.md`](../examples/qa/LANGFUSE.md)
