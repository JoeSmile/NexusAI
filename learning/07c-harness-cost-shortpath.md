# 07c — 深挖 C：短路径 · 成本 · LLMHarness

> 面试目标：讲清「钱在哪一步花、何时可以 $0、统一出口多了什么」。  
> **范围：** Chat DAG 内 short/long（[05b](05b-pipeline-nodes.md)）。Runner 节点若调 LLM，**同样必须走 Harness**，禁裸 SDK。  
> 锚点：`model_router.py` · `llm_generate.py` · `harness/llm.py` · `cost_manager.py` · …  
> 速记附录：[harness.md](harness.md)

---

## 0. 一张图说完

```text
analyze_parallel 产出 intent + confidence
        │
        ▼
   model_router
        │
        ├─ confidence≥0.85 且有 skill
        │     → execute_skill → finish_reason=skill_executed
        │     → total_cost=0 → conversion_hook → END
        │        （图边：route_short_or_long ≠ llm_generate）
        │
        └─ 否则 long path
              → select_model_for_intent(+A/B override)
              → estimate_cost 写入 state
              → 注入租户 LLM key（DB 解密 / env fallback）
              → finish_reason=routed_to_llm
                    │
                    ▼  (非 stream)
              llm_generate
                    │
                    ▼
              LLMHarness.generate
                 ① estimate_cost + check_budget → 失败 COST_001
                 ② mock | replay | record/openai(_call_api + key chain)
                 ③ calculate_cost + record_consumption + LangFuse usage
                    │
                    ▼
              guardrails_output → write_memory → conversion_hook → END
```

**面试一句话：**
短路径在 `model_router` 就结束且标 `$0`；长路径只允许 `finish_reason==routed_to_llm` 且非流式时进 `llm_generate`；**所有真实/模拟 LLM 调用都穿 `LLMHarness`**，预算与记账在入口统一做。

---

## 1) 短路径（Skill）— 面试官最爱问「怎么省钱」

### 触发条件（两道门）

源码：`backend/pipeline/nodes/model_router.py`

1. `intent_confidence >= 0.85`
2. `SkillRegistry.get_skill_for_intent(intent, confidence)` 能命中（内部再次校验 threshold，默认也是 0.85）

命中后：`execute_skill` → 写 `response` / `finish_reason` / `total_cost=0.0`，**直接 return**，不再选模型、不注入 key。

### 条件边（防「错误还去调 LLM」）

`route_short_or_long` **反向判断**：

- 仅当 `finish_reason == "routed_to_llm"` **且** `not stream_mode` → 去 `llm_generate`
- 其余（skill 成功/失败/error/流式）→ `conversion_hook`

**为什么重要（面试故事）：**
曾有坑：skill 失败若漏判进 LLM，会**吞掉错误 + 双份成本 + 审计不一致**。所以不枚举「哪些算短路径结束」，而是「只有明确 routed_to_llm 才花钱」。

### Skill 注册

`backend/skills/registry.py`：扫描 `builtin/`，按 `trigger_intents` 建 intent→skill_id。
内置例：greeting。实体来自 `state["entities"]`（现状管线里常为空——诚实说即可）。

### 观测

短路径可降采样：`_maybe_disable_short_path_trace` → `should_sample(finish_reason)` 未命中则关后续 tracing，省 LangFuse 噪声。

### 面试官问 / 求职者答

| 问 | 答 |
|----|-----|
| 短路径一定不花钱？ | 设计上 `total_cost=0`，不调 Harness；skill 自己若调外部 API 是另一回事，当前 builtin 是本地逻辑 |
| 阈值为何 0.85？ | 意图不稳时宁可走 LLM，避免错 skill；可讲「高置信才截断」 |
| 流式为何不进 llm_generate 节点？ | `stream_mode` 时边指到 conversion；流式由 router 侧 `_ainvoke_streaming` / Harness.stream 另路径承载——别把「节点图」和「SSE 出口」说成同一条 |

---

## 2) 长路径选模 — 钱的「估价」从哪来

### 模型选择

`select_model_for_intent(intent)`（`model_registry.py`）：

| intent（例） | tier |
|--------------|------|
| greeting / chat | cheap |
| knowledge_query / advice / function | good |
| 其他 / default | best |

同 tier 取 `cost_per_1k` **最低**；无候选再按 best→good→cheap 回退。

A/B：`ab_variant_config.model` 可覆盖；覆盖无效则回落 `select_model_for_intent`。

### 写入 state（还没真正扣费）

- `selected_model` / `estimated_cost`（`estimate_cost(name, max_tokens)`）
- `finish_reason = "routed_to_llm"`
- `llm_key_provider`、可选 `llm_base_url`
- 租户 key：`LLMKeyRepository.get_key(tenant, provider)`；无则 `spec.api_key_ref` → env

**面试点：** router 阶段是 **选路 + 估价 + 备钥匙**；扣预算与记实际成本在 Harness。

---

## 3) LLMHarness — 统一出口（核心加分）

文件：`backend/core/harness/llm.py`
管线入口：`llm_generate` → `harness.generate(...)`

### generate 五步（按代码顺序）

```text
1. estimate_cost(model, max_tokens)
2. check_budget(tenant_id, estimated) → 失败返回 COST_001，不调 API
3. count_tokens(messages) 作 input 估算
4. wrap(_call):
      provider = get_llm_provider()
      · mock   → mock_response
      · replay → load_fixture，miss 则 mock
      · record / openai → _call_api（真实 + key failover；record 成功可 save_fixture）
5. 成功后：calculate_cost → record_consumption(metrics)
   + LangFuse update_current_observation(usage)
```

### Provider 模式（离线/CI/实网）

| `LLM_PROVIDER`（概念） | 行为 |
|------------------------|------|
| mock | 不打外网，固定/启发式回复 |
| replay | 读录制 fixture，保证可重复 QA |
| record | 真调用并落 fixture |
| openai（及兼容） | 真调用，走 key chain |

**面试话术：** Harness 把「测得动 / 录得下 / 生产可切 key」收成一个门面，业务节点不直接 `AsyncOpenAI(...)`。

### `_call_api` + key failover

1. `get_key_chain(tenant, provider, limit=3)`
2. 链空 → 用传入 api_key / `LLM_API_KEY` / `OPENAI_API_KEY` 拼单节点 fallback
3. `call_with_key_failover(chain, _once)`：单次用 OpenAI-compatible `chat.completions.create`；429/401 沿链切换并回写冷却（Task 27）

图上 CALLS：`generate → estimate_cost/check_budget/wrap/calculate_cost/record_consumption`；`_call_api → get_key_chain/call_with_key_failover`。

### llm_generate 细节（别漏）

- 用户消息优先 `raw_input`（保留原始），system 可来自 A/B `system_prompt`
- `max_tokens` 来自 ModelSpec
- 失败：非 `COST_001` 走 `get_fallback("zh")`；预算拒绝直接把 Harness 文案给用户
- `finish_reason`：成功 `llm_generated`；失败用 error 码

---

## 4) 成本账 — 估价 / 预算 / 实扣

文件：`backend/core/cost_manager.py`

| API | 作用 |
|-----|------|
| `estimate_cost(model, max_tokens)` | `_price * max_tokens/1000`；价来自 ModelSpec.cost_per_1k 或 `COST_TABLE` |
| `check_budget(tenant, estimated)` | 读 `tenant_config.config.budget.daily_limit`（默认 10）；**仅比较本次估价是否 > daily_limit**，不是累计日消耗硬闸（诚实讲清） |
| `calculate_cost(model, total_tokens)` | 实扣用粗算 token |
| `count_tokens` | 中文×2 + 英文/4 + 10（粗略，非 tiktoken） |
| `record_consumption` | Prometheus：`cost_total` / `tokens_total`（按 tenant+model） |
| `cost_summary` | 可从 `audit_logs` 聚合（报表侧） |

### 诚实边界（面试加分）

1. **预算检查偏简**：当前是「单次估价 vs daily_limit」，不是严格的「今日已花 + 本次」。V2 预算语义在 Task 32 冻结区——可说「我知道缺口」。
2. **token 粗算**：够排序与演示，不适合财务级对账。
3. **短路径不进 Harness**：故无 `record_consumption`；成本为 0 写在 pipeline state。
4. **cache hit** 更早 END，同样不进 Harness（另一条 $0 路径）。

### 「钱在哪一步」对照表

| 路径 | 是否调 LLM | 成本写入 |
|------|------------|----------|
| cache hit | 否 | 无 / $0 语义 |
| guard/gate block | 否 | 无 |
| short skill | 否 | `total_cost=0` |
| long + COST_001 | 否（被拒） | 失败，无成功消费 |
| long + mock/replay/openai | 是（或模拟） | Harness metadata + metrics；管线 `total_cost` |

---

## 5) 三维速记（本专题）

### 图怎么说

- Hotspot 簇：`stream/generate/complete_via_provider/LLMKeyRepository/get_key_chain`
- 管线边：`model_router` → 条件 → `llm_generate` | `conversion_hook`
- 所有花钱调用应能追到 `LLMHarness`（旁路若直调 API 就是债）

### 面试官可能追问

1. short 失败会不会误调 LLM？→ 讲 `route_short_or_long` 反向判断
2. 预算超限用户看到什么？→ `COST_001` 文案，不走 fallback 套话
3. 多 key 如何切换？→ chain + failover，冷却键
4. 和 Capability 的 LLM 调用是否同一套？→ 理想应复用 Harness；若有旁路要承认并指方向
5. 为何 intent→tier？→ 简单意图用 cheap，控制账单；同 tier 选最便宜

### 求职者 60 秒口述稿

> 过完意图后，`model_router` 先看置信度：够高且有 Skill 就本地执行，成本记 0，条件边不会进生成节点。
> 否则按意图档位选模型、估价、取租户 key，标记 `routed_to_llm`。
> 真正调用只走 `LLMHarness`：先预算预检，再按 mock/replay/record/openai 执行；真调用带 key 链故障转移；成功后记 token/成本并打到 LangFuse。
> 这样治理层能回答三个问题：这次花没花、花在哪个模型、钥匙挂了有没有备胎。

---

## 6) 建议自测（开口前 10 分钟）

不看笔记，默写：

1. short 的两个条件 + 条件边规则
2. `generate` 五步顺序
3. `COST_001` 与 skill error 在图上分别走到哪
4. `estimate_cost` vs `calculate_cost` vs `check_budget` 各用什么输入

对照文件：

```bash
# 只读复习
sed -n '19,108p' backend/pipeline/nodes/model_router.py
sed -n '33,115p' backend/core/harness/llm.py
sed -n '37,78p' backend/core/cost_manager.py
sed -n '124,148p' backend/core/model_registry.py
```

---

## 7) Harness 层还能怎么更好（面试加分：现状 → 缺口 → 改法）

> 定位：下面不是空喊「再加功能」，而是对照**当前代码真实缺口**。面试官问「你会怎么演进」时，按 P0→P2 讲。

### 7.1 现状已经做对的

| 能力 | 落点 |
|------|------|
| 统一 generate 入口 | 预算预检 → provider 分流 → 记账 → LangFuse usage |
| 底座韧性 | `Harness.wrap`：断路器 + 最多 3 次指数退避 + 超时 |
| 非流式 key 链 | `_call_api` → `get_key_chain` + `call_with_key_failover` |
| 可测性 | mock / record / replay / openai |

### 7.2 缺口清单（按优先级）

#### P0 — 流式与非流式能力不对齐（可靠性）

**现状：** `generate` 走 key failover；`stream` 真流式路径只用**单把** `api_key`（或 env），`AsyncOpenAI` 直连，**不走** `get_key_chain` / `call_with_key_failover`。失败才整段降级 `generate`（此时才有链）。

**问题：** 生产 SSE 是主路径时，429/401 无法热切换 key；用户先看到半截流再整段重来，体验差。

**改法：**
1. 抽 `_streaming_once(plain_key, url)`，用与 `_call_api` 相同的 chain + failover 包装（流式失败切下一把再开新 stream）。
2. 或：首包前用 chain 选健康 key，stream 中途 401 再 failover（实现更难，可二期）。
3. 验收：单测「第一把 429 → 第二把出 token」，与 `tests/test_key_failover.py` 对齐。

**面试一句话：** 「非流式钥匙链齐了，流式还是单钥匙——这是我优先补的对称性。」

---

#### P0 — 预算闸门偏「示意」、未真累计（治理可信度）

**现状：** `check_budget` 读 `tenant_config.budget.daily_limit`，判断的是 `estimated_cost > daily_limit`，**不是**「今日已消耗 + 本次估价」。

**问题：** 治理叙事里「控成本」会被懂行的面试官拆穿；指标 `record_consumption` 与闸门数据源不一致。

**改法（从小到大）：**
1. **V1.x 小步：** Redis/DB 记 `tenant:cost:YYYYMMDD`，`check_budget` 用 `spent + estimated <= daily_limit`；与 `record_consumption` 同路径递增。
2. **V2（Task 32）：** 三级预算 / 审批放行 / 两本账——面试提路线即可，不假装已做。

**面试一句话：** 「闸门和 Prometheus 计数现在是两套；下一步让 spent 进同一本账。」

---

#### P1 — Token / 成本精度（对账与选型）

**现状：** `count_tokens` = 中文×2 + 英文/4 + 10；价目 `COST_TABLE` / `cost_per_1k` 粗粒度；未吃 API 返回的 `usage`。

**问题：** 报表、预算、模型比价都会漂；和厂商账单对不上。

**改法：**
1. `_call_api` / stream 结束优先用 `response.usage`（prompt/completion tokens）。
2. 无 usage 时再 fallback 粗算，并在 metadata 标 `token_source=estimate|provider`。
3. 价目表按 input/output 分列（多数模型单价不同）。

---

#### P1 — 调用面未完全收口（旁路漏治）

**图/grep 事实：** 主链 `llm_generate` / capability `invoke` / pipeline SSE 用 `LLMHarness`；另有 `modules/llm/providers/openai_provider.py`、`harness/llm_client.py`（LangChain）、历史 `enhanced_chat_service` / `optimized_chat_service`、agent 路径等仍可能直调或平行客户端。

**问题：** 旁路绕过预算、failover、统一 usage → 「治理层」故事出现窟窿。

**改法：**
1. 约定：**业务代码禁止直接 `AsyncOpenAI`**（除 harness / key_health 探活）。
2. Lint/审计脚本扫 `AsyncOpenAI(` 调用点（可挂 `scripts/audit_consistency.py`）。
3. RAG/intent/agent 逐步改走 `LLMHarness` 或薄封装 `get_llm_client()` 且内部仍进同一记账。

**面试一句话：** 「出口统一是目标态；我能量化还有几处旁路，并按调用量收口。」

---

#### P1 — `stream` 未吃满 `Harness.wrap`（韧性不一致）

**现状：** `generate` 经 `wrap`（断路器/重试/超时）；`stream` 自管循环，断路器/统一超时较弱；降级到 `generate` 时可能**二次** `check_budget` / 重复记账风险要核对。

**改法：**
1. 流式也登记 breaker（按 provider+model 维度，避免一个坏 upstream 打满）。
2. 降级路径：若 stream 已 `record_consumption` 则 generate 降级需跳过重复计费（idempotent 标记）。
3. 超时：首 token 超时 vs 整段超时分开配置（TTFT vs total）。

---

#### P2 — Provider 与多模型生态

| 点 | 现状 | 更好 |
|----|------|------|
| 协议 | OpenAI-compatible 为主 | 显式 adapter：`openai` / 国产兼容 / 本地 vLLM，健康检查复用 `key_health` |
| Fixture key | `sha256(model+messages)` 裸消息 | 与 chat normalize 对齐，减少 replay miss |
| mock | 回显片段 | 按 intent 可脚本化剧本（演示「短路径 vs 长路径」对比更稳） |
| 结构化输出 | 未一等公民 | `generate_structured(schema)` + 校验失败重试（护栏/意图可复用） |

---

#### P2 — 可观测与成本归因

**现状：** LangFuse usage 在成功路径 update；错误分类偏字符串；stream 取消（client abort）的部分消耗未必记。

**改法：**
1. 统一 `HarnessResult`：`error_code` 枚举（`COST_001` / `LLM_429` / `LLM_401` / `TIMEOUT`…），对接 `errors_total`。
2. 取消/半截流：记 `partial_tokens` + `finish_reason=cancelled`。
3. metadata 固定带：`tenant_id, model, provider, key_id, path=stream|generate, token_source`。

---

### 7.3 建议演进顺序（可当「30 天计划」口述）

```text
1) stream 对齐 key failover + 避免降级双记账     ← 用户可感知、风险最高
2) 日累计预算 spent 与 record_consumption 同源   ← 治理叙事站得住
3) 吃 provider usage + 分 input/output 计价       ← 数字可信
4) 扫清 AsyncOpenAI 旁路                          ← 出口唯一
5) 结构化输出 / adapter / fixture 归一化          ← 体验与生态
```

与管线侧 Task 39（早预处理降无效流量）互补：**39 减少打到 Harness 的请求；Harness 优化让打到的请求更稳、更可计量。**

### 7.4 面试官追问速答

| 问 | 答 |
|----|-----|
| Harness 最大短板？ | 流式未走 key 链；预算未真累计 |
| 为什么先修 stream？ | 演示/生产主路径是 SSE；非流式 failover 救不了主路径 |
| 会不会过度设计？ | 先对齐已有 `call_with_key_failover`，不新造框架 |
| 和 Dify 比？ | 我们不拼编排器，拼「每次调用可审计可熔断可切 key」的出口层 |

---

## 8) 和下文衔接

- 预算「真累计 / 审批放行」→ Task 32（V2 冻结），与 §7.2 P0 预算小步可并行叙事
- 早退降本（normalize / cheap gate / 推迟 memory）→ Task 39
- 下一深挖可选：**B Pipeline 节点顺序** 或 **A Auth**（短路径之上的身份前提）


Harness 层优先优化（口述用）
P0

流式未走 key 链 — generate 有 failover，stream 仍单 key；SSE 主路径最该先对齐
预算未真累计 — 现在是「单次估价 vs daily_limit」，要和 record_consumption 合成日 spent
P1 3. 吃 API usage，别只靠粗算 token
4. 收口旁路 AsyncOpenAI（provider / 旧 chat service / agent）
5. stream 补齐断路器/超时，降级时避免双记账

P2
多 provider adapter、fixture 归一化、结构化输出、取消半截流的用量归因

演进顺序叙事：先让 SSE 和钥匙链对称 → 预算一本账 → 数字可信 → 出口唯一；管线 Task 39 负责少打到 Harness，Harness 负责打到的更稳、更可计量。
