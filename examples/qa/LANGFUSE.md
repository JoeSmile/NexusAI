# LangFuse 配合 QA 查看指南

> 服务: `http://localhost:3001`(容器 contextgate-langfuse-1;独立库,由 postgres initdb.d 建)
> 本文档基于 2026-08-02 实测(经 Langfuse Public API 核验),写明「哪些 QA 能配合看、指标怎么读、
> 何时要优化、error 怎么解、再深入怎么查」。

## 1. 哪些 QA 可以配合 LangFuse 看

| QA 项 | 是否进 LangFuse | 说明 |
|-------|----------------|------|
| 03-chat 3.2 长路径 | ✅ 全量采样 | trace 名 `chat.pipeline`,节点 span 齐全,llm_generate 带成本/用量 metadata |
| 03-chat 3.1 短路径(greeting) | ⚠️ 10% 采样 | `LANGFUSE_SAMPLE_SHORT_PATH`(默认 0.1);不一定每次出现 |
| 03-chat 3.3 缓存命中 | ⚠️ 低采样 | cache_hit 属短路径;出现时无 llm_generate span |
| 03-chat 3.4 注入 / 3.5 PII / 3.6 密钥 | ⚠️ 低采样 | blocked 属短路径;看 guardrails_input/output 的 input/output |
| 11-sec 11.2/11.5/11.6 | ⚠️ 同 3.4-3.6 | 同上 |
| 05-intent | ❌ 不进 | 无 LLM/未挂 observe;看接口响应 |
| 06-rag | ❌ 不进 | RAG 服务未挂 observe(见 §6 GAP-08);看 `/api/rag/status` + redis 键 |
| 07-agent / 09-eval | ❌ 不进 | 未挂 observe(见 §6) |
| 10-obs 10.1/10.2 | ✅ LangFuse 本体 | 浏览器直接看 trace 列表 |

**排查入口总原则:** 先记响应体里的 `trace_id`(chat 响应含 trace_id 或 error.trace_id),再到 LangFuse
搜索;采样裁掉时以服务日志为准。

## 2. LangFuse 关键指标的含义

| 指标 | 含义 | 当前状态(2026-08-02 实测) |
|------|------|---------------------------|
| Trace(`chat.pipeline`) | 一次 `/chat` 请求全链路 | 存在;延迟 0.1ms(失真,见 GAP-08) |
| SPAN(`pipeline.*`) | 各管线节点(auth_check→…→write_memory) | 挂在 trace 下但**平铺**(parent=None,无树结构) |
| GENERATION(`pipeline.llm_generate`) | 模型调用 | metadata 有值,usage/cost 字段为空(见 GAP-08) |
| span.metadata.path | `long`(LLM 生成)/ `short`(skill/缓存/拦截) | ✅ 准确,最可信的路径标记 |
| span.metadata.total_cost | 本次 LLM 成本(美元;replay 模式为估算) | ✅ 准确(与响应 total_cost 一致) |
| span.metadata.total_tokens | 本次 token 消耗 | ✅ 准确 |
| span.metadata.ab_variant | A/B 实验变体(A/B/None) | ✅ 准确(experiment_hook 打标) |
| span.usage | input/output tokens | ❌ 全 0(已知问题) |
| span.latency | 节点耗时 | ❌ ≈0(已知问题) |

> **实测结论:** LangFuse 里当前「可信」的是 trace 存在性、metadata(path/cost/tokens/ab_variant);
> 「不可信」的是延迟、usage、父子树结构。真实延迟以响应体 `pipeline_latency_ms` 为准。

## 3. 什么情况说明需要优化(从 LangFuse 看什么)

| 现象 | 含义 | 动作 |
|------|------|------|
| 长路径(trace 里出现 llm_generate)占比高 | 意图路由没接住,本该 skill/缓存的走了 LLM | 查 intent 置信度、skill 注册、缓存是否生效(对照 §3.3 / rag status) |
| metadata.total_cost 偏高 | 长路径多或 token 大 | 查 build_context 是否塞了过多上下文;查模型路由配置 |
| total_tokens 异常大 | 上下文膨胀 | 检查 load_memory/build_context 的窗口与截断 |
| blocked 频繁 | 输入护栏误伤 或 真实恶意流量 | 调护栏阈值/模式;看 guardrails_input 的 input 判定 |
| cache_hit 很少 | L1/L2 缓存没生效 | 对照 `/api/rag/status` 的 cache 字段与 redis 键 |
| ab_variant 分组差异明显 | 实验组显著不同 | 展开 experiment_hook 的 metadata 分析 |
| 找不到 trace | 短路径被采样裁掉,或请求没走 chat 管线 | 看采样配置;或直接查服务日志 |

## 4. error 的含义

**结构化错误码(响应体 `error.code`)——第一排查入口:**

| code | 含义 | 处理 |
|------|------|------|
| `AUTH_001` | 缺少 API Key | 请求头补 X-API-Key |
| `AUTH_002` | Key 无效/已删除 | 重新铸造;检查 admin 是否删了 key |
| `AUTH_003` | 权限不足(角色不匹配) | 换有对应权限的角色 key(见 02-auth 矩阵) |
| `RATE_001` | 限流(HTTP 429) | 稍后重试;压测场景属预期(见 06-rag §6.10) |
| `FILE_002` | 文件类型不允许 | 内容头校验失败(见 11.3 MIME 伪造) |
| `SYS_001` | 内部错误(detail 有 pydantic/SQL 详情) | 记 detail 报给开发;多为数据/模型字段不符 |
| `blocked`(finish_reason) | 输入/输出护栏拦截 | **不是错误**——安全防护生效,正常现象 |

**LangFuse 侧的 error:** 当前 trace/span 的 status 大多为 None(见 GAP-08),不能依赖 UI 红标;
错误排查 = 响应 error.code + 服务日志(uvicorn stdout)+ trace_id 交叉定位。

## 5. 有问题怎么进一步优化(深入路径)

1. **定位**: 响应 `trace_id` → LangFuse 搜 trace(存在时)→ 看哪些 span 的 metadata 缺失/异常
2. **路径分析**: `metadata.path=long` 却预期 short → 查 intent(detect 接口)+ skill 注册表;
   `cache_hit` 却没命中 → 查 redis 键与 epoch(见 10.7/10.8)
3. **成本分析**: total_cost 高 → 看模型路由(registry 是否选了贵的模型)+ total_tokens(上下文窗口)
4. **护栏分析**: blocked 频发 → 调 guardrails 模式/阈值;误伤 vs 真实攻击用 input span 的原始文本判断
5. **链路对比**: AB 变体差异 → experiment_hook 的 ab_experiment_id/variant 分组看
6. **结构性问题(GAP-08)**: span 树断裂/延迟失真 → 方案见下节,决策后实施

## 6. 已知问题(2026-08-02 实测)

**GAP-08 [Important,待审核] — LangFuse span 树/延迟/用量失真:**
- 节点 span 全部平铺(`parent_observation_id=None`),DAG 父子关系丢失,UI 看不到「树」
- span 的 start/end_time 缺失 → latency≈0;usage 全 0;cost 未上 span(只在 metadata)
- RAG / Agent / Eval 模块未挂 `@observe`,完全不进 LangFuse
- 根因候选: LangGraph 内部 task 使 Langfuse SDK 的 contextvars 上下文中断;修复候选:
  ① 官方 `langfuse-langgraph`/CallbackHandler 集成(推荐,专用支持);
  ② 在 graph 外层手动创建 span + 显式传 trace_id 给节点;
  ③ 至少给 rag ask 挂 `@observe` 让 RAG 进 LangFuse(成本/用量至少可见)。
- **影响**: 10-obs 10.1/10.2 的「span 树定位」演示当前不成立,应展示 metadata 分析 + 响应延迟替代;
  修复后再启用「树」叙事。

> 排查脚本(Public API): `LANGFUSE_PUBLIC_KEY/SECRET_KEY/HOST` 在 config.env,
> `curl -u <pub>:<sec> $HOST/api/public/traces?limit=5` 可看 trace 列表与 observation 树。
