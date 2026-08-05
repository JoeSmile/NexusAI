# 05b — 深挖 B：Pipeline 全节点与条件边

> 面试目标：白板默画 DAG、说清每个条件边「为什么在这」、早退路径花不花钱。  
> 锚点：`backend/pipeline/graph.py` · `router.py` · `state.py` · `nodes/*` · `langgraph_compat.py`  
> 关联：短路径/Harness 细节见 [07c](07c-harness-cost-shortpath.md)；早预处理演进见 Task 39。

---

## 0. 总图（与代码一致）

```text
HTTP POST /chat
  Depends(require_permission("chat:write"))  ← 真认证在这里
  → _run_chat_pipeline → make_initial_state → compiled_graph.ainvoke
       → 成功：log_audit + ChatResponse
       → RATE_001 等：ContextGateException 上抛
       → finally：LangFuse flush 或 discard（短路径可降采样）

图内：
auth_check
  → load_memory
  → rate_limiter          （超限抛 RATE_001，不走 END 正常边）
  → cache_check
       ├─ hit  → END                    （无 conversion_hook）
       └─ miss → guardrails_input
                    ├─ block → END      （无 conversion_hook）
                    └─ pass  → analyze_parallel
                                 → build_context   （写 raw_input = 记忆+用户）
                                 → experiment_hook
                                 → model_router
                                      ├─ short/error/stream → conversion_hook → END
                                      └─ routed_to_llm（非 stream）
                                           → llm_generate
                                           → guardrails_output
                                           → write_memory
                                           → conversion_hook → END
```

**13 个节点 + 3 条条件边**（cache / guard / short-long）。  
引擎：优先官方 LangGraph；否则 `langgraph_compat` shim（`ainvoke` 循环 + 防环 100 步）。

---

## 1) 入口层（图外，必须会讲）

| 层 | 做什么 | 不做什么 |
|----|--------|----------|
| `verify_api_key`（Depends 链里） | Header → SHA256 → `TenantContext` | 不在图节点里再验 key |
| `require_permission("chat:write")` | RBAC / 应用权限 | — |
| `chat_pipeline` / `_run_chat_pipeline` | 组 state、`ainvoke`、审计、采样 flush | 不把业务逻辑堆在路由里 |
| `auth_check` 节点 | 仅保证 `user_context` 有默认值 | **不是**第二道认证 |

**面试陷阱：** 「管线第一个节点做认证」——错。认证在 FastAPI；节点是注入/兜底。

---

## 2) 逐节点速查（面试卡片）

### ① `auth_check`
- **输入/输出：** 补齐 `user_context`
- **不做：** 查库验 key
- **失败模式：** 几乎不失败

### ② `load_memory`
- **做：** `UnifiedMemoryService.read` → `hot/warm/cold` 进 state
- **位置争议：** 在 cache/guard **之前** → hit/block 仍付记忆 I/O（Task 39 要后移）
- **诚实：** `session_id=None` 传给 read（看实现：跨会话聚合还是默认会话——开口前再扫一眼 `memory_service.read`）

### ③ `rate_limiter`
- **做：** `check_rate_limit(tenant_id)`；失败写 `RATE_001` 后 **`raise ContextGateException`**
- **与 END 不同：** 不走条件边收尾，由 router 异常路径处理
- **面试：** 限流是「硬中断」，不是 `finish_reason` 软结束

### ④ `cache_check`
- **做：** exact key `exact:{tenant}:{user}:{hash(message)}`；可选 template `template:{tenant}:{fingerprint}`（廉价 greeting 指纹或 state 内指纹）
- **命中：** `cache_hit=True`，`finish_reason=cache_hit`，响应直接填好
- **条件边：** `should_skip_to_end` → hit 则 **END**（跳过 conversion_hook）
- **诚实债：** hash **无 normalize**（`"你好"`≠`"你好 "`）；写回在 `write_memory` 且受 `LLM_MOCK` 等条件约束——读写语义要对齐讲清

### ⑤ `guardrails_input`
- **做：** `check_input` → 注入 **block**（`GUARD_001`）/ PII **redact**（改 `message`）/ 超长现状偏截断
- **条件边：** `should_block_to_end` → block 则 END
- **trade-off：** 放在 cache **之后**——假设缓存只存干净答案；若写路径被污染，hit 会跳过护栏（要会说风险）

### ⑥ `analyze_parallel`
- **名实：** `asyncio.gather` 里目前主要是意图一项；`entities` 在 `_analyze_intent` 里 **恒 `{}`**
- **做：** 调 intent 模块同源分类器；写 `intent` / `intent_confidence` / `fingerprint`
- **降级：** 异常 → `default` + confidence 0.5（偏保守进长路径/best 档逻辑）

### ⑦ `build_context`
- **做：** 用已载入记忆 `assemble_prompt_block`；记忆漂移则只留隔离头；拼进 **`raw_input`**
- **关键：** `llm_generate` 读的是 `raw_input`（不是裸 `message`）→ 记忆**会**进模型（经 raw_input 重写）
- **注意：** 初始 state 里 `raw_input==message`；本节点之后才是「记忆+用户」

### ⑧ `experiment_hook`
- **做：** 确定性分流、写 `ab_*`、记曝光；variant 可改 model / system_prompt 等
- **位置：** 在 router 前，故能影响选模与生成

### ⑨ `model_router` → 详见 [07c](07c-harness-cost-shortpath.md)
- short：skill，`total_cost=0`
- long：选模、估价、灌 key，`finish_reason=routed_to_llm`
- **条件边：** 仅 `routed_to_llm` 且非 `stream_mode` → `llm_generate`；否则 `conversion_hook`

### ⑩ `llm_generate`
- **做：** `LLMHarness.generate`；失败 fallback / `COST_001`
- **流式：** 图边常不进本节点；SSE 在 `router.chat_streaming` 另走 Harness.stream

### ⑪ `guardrails_output`
- **做：** 输出侧检查/脱敏；长路径专属（short 不经此节点）

### ⑫ `write_memory`
- **做：** `write_turn` + 可选 cold 摘要；mock 等条件下写 exact/template cache；插 `audit_logs`（节点内也有审计 SQL——与 router `log_audit` 分工要诚实：可能双通道，开口说「router 收尾 audit + 节点写库」时以代码为准核对）
- **仅长路径到达**（short 从 model_router 直去 conversion）

### ⑬ `conversion_hook`
- **做：** 有实验且有最终响应时记 conversion；DB 挂了不拖垮管线
- **不到达：** cache hit / input block 直接 END 时**不经过**本节点

---

## 3) 三条条件边（背熟）

| 边 | 函数 | end / continue 含义 |
|----|------|---------------------|
| cache | `should_skip_to_end` | hit→END；miss→guardrails |
| guard | `should_block_to_end` | block→END；pass→analyze |
| router | `route_short_or_long` | 反向：仅 `routed_to_llm`∧¬stream → llm_generate；其余 conversion |

**设计原则口述：**  
早退越靠前越省钱；花钱节点（LLM）前尽量完成「身份、配额、缓存、安全、意图」；短路径错误不得漏进 LLM。

---

## 4) 路径 × 成本 × 是否写记忆

| 路径 | 典型 `finish_reason` | 调 LLM？ | load_memory？ | write_memory？ | conversion_hook？ |
|------|----------------------|----------|---------------|----------------|-------------------|
| cache hit | `cache_hit` | 否 | 是（现状） | 否 | 否 |
| rate limit | `RATE_001` 异常 | 否 | 是 | 否 | 否 |
| input block | `blocked` | 否 | 是 | 否 | 否 |
| short skill | `skill_executed` / error | 否 | 是 | 否 | 是 |
| long OK | `llm_generated` | 是 | 是 | 是 | 是 |
| budget | `COST_001` | 拒在 Harness | 是 | 是* | 是 |

\*长路径失败仍可能经过 write/guard 后续边——以 `finish_reason` 非成功时 write 是否空写为准，面试可说「会走到收尾节点，写入内容取决于实现」。

---

## 5) 状态与可观测

### `PipelineState`（TypedDict，非 Pydantic）
身份 / message·raw_input / 三层记忆 / intent·fingerprint·cache / 护栏标志 / 选模与 key / response·finish_reason / 成本延迟 / A/B / stream_mode …

### LangFuse 嵌套（GAP-08）
`_lf_node` 把根 trace/span id 经 state 传入每个节点，避免 LangGraph 丢 contextvar 导致平铺根 span。

### 采样
短路径可 `set_tracing_enabled(False)`；router `finally` 里 `flush` vs `discard`。

---

## 6) 三维速记

### 图怎么说
- `pipeline` 包 fan-out 到 `core`；入口 `build_pipeline` / `_run_chat_pipeline`
- 热点边在 `routers→core`，但 **业务故事在 DAG 条件边**

### 面试官爱问

1. 为何 cache 在护栏前？→ 性能；前提是写路径干净  
2. 为何 load_memory 这么早？→ 历史顺序；承认浪费，指向 Task 39  
3. auth_check 验什么？→ 几乎不验，Depends 已验  
4. analyze 并行了什么？→ 目前意图为主，实体空  
5. short 失败会进 LLM 吗？→ 不会，反向条件边  
6. 记忆怎么进模型？→ `build_context` 写入 `raw_input`，`llm_generate` 读它  
7. hit 为何不记 conversion？→ 边直接 END；A/B 转化只覆盖走到 hook 的路径  

### 求职者 60 秒口述

> Chat 请求在 FastAPI 完成认证和权限后，进入 LangGraph 管线。  
> 先注入上下文、拉记忆、限流、查缓存；命中直接结束。  
> 未命中过输入护栏，再意图分析、把记忆拼进 raw_input、做 A/B，然后模型路由：高置信 skill 零成本收尾，否则走 LLMHarness 生成，再出站护栏、写记忆与转化事件。  
> 整条链的价值是把「不该发生的事」变成显式节点和可早退的边，而不是 middleware 黑盒。

---

## 7) 管线层还能更好（对照 Task 39 + 诚实债）

| 优先级 | 点 | 现状 | 更好 |
|--------|----|------|------|
| P0 | 归一化 + query_hash | 裸 hash | 与 RAG 同 normalize；读写同一 key |
| P0 | cheap gate | 无 | 空/超长/deny-list 早于贵 I/O |
| P0 | 推迟 load_memory | auth 后立刻 | miss+guard pass 后再读 |
| P1 | analyze 名实 | entities 空、gather 单任务 | 真并行实体或改名 |
| P1 | cache hit / block 与 A/B | 直 END | 若要实验完备，收口经 conversion 或显式「skip 转化」文档化 |
| P1 | rate_limit 与软结束 | 抛异常 | 统一 finish_reason 路径便于审计字段一致 |
| P2 | stream 与图 | stream_mode 绕开 llm_generate 节点 | 文档/图示把 SSE 旁路画清楚，避免面试画混 |
| P2 | write_memory 与 router 审计 | 可能双写通道 | 单一 audit 出口 |

演进叙事与 07c 对齐：**管线少送无效请求进 Harness；Harness 让有效请求可计量可切 key。**

---

## 8) 自测（10 分钟）

不看笔记默写：

1. 13 节点顺序 + 3 条件边  
2. 哪些路径不经 `conversion_hook` / 不经 `write_memory`  
3. `raw_input` 在哪一步从「纯用户句」变成「记忆+用户」  
4. `auth_check` vs `verify_api_key` 分工  

```bash
sed -n '63,122p' backend/pipeline/graph.py
sed -n '100,108p' backend/pipeline/nodes/model_router.py
sed -n '15,45p' backend/pipeline/nodes/build_context.py
```

---

## 9) 衔接

- 深挖 C（钱与 Harness）→ [07c](07c-harness-cost-shortpath.md)  
- 设计中的重排 → `tasks/39-pipeline-early-preprocess.md`  
- 下一深挖可选：**A Auth/RBAC** 或 **D RAG + Capability**
