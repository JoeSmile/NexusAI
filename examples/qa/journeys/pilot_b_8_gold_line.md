# Pilot B · 金线 8 — 组合编排（Wave 8）

> **状态:** 剧本可复跑（API 驱动；无画布依赖）  
> **设计:** [`docs/superpowers/plans/2026-08-05-pilot-b-composition-runtime.md`](../../../docs/superpowers/plans/2026-08-05-pilot-b-composition-runtime.md) §6  
> **任务:** [`tasks/40/W8-composition.md`](../../../tasks/40/W8-composition.md) 40.84  
> **证据:** `examples/qa/journeys/evidence/8/`  
> **建议:** `LLM_PROVIDER=mock`（内容审 V1 后置；演示生成链勿依赖未实现的 `AUTO_PUBLISH_CONTENT`）

## 剧本（可勾）

| # | 步骤 | 验收 | 状态 |
|---|------|------|------|
| 1 | 发布父/子组合 workflow（声明式 IR：`kind=workflow` + edges） | `POST /workflows` → publish | ✅ 脚本 06-09 |
| 2 | 根 run：`POST /workflows/{id}/runs` body `{ "input": {...} }` | run pending→running；`run_inputs` 可读 | ✅ 脚本 10 |
| 3 | 子 run 由 Runner 内部 `start_run(_internal_nested=True)` | `GET /runs/{parent}/children` 非空 | ✅ 脚本 11 |
| 4 | 伪造 `parent_run_id` 被拒 | `403 PARENT_FORGED` | ✅ 单测 `test_workflow_nesting` |
| 5 | 子挂起时父节点 `waiting_child`，父 run 仍 `running` | 非误标 cancelled | ✅ 脚本 12 |
| 6 | `POST /runs/{id}/execute` 在 waiting_child 时 | `409 WAITING_CHILD` | ✅ API 已实现 |
| 7 | agent 节点同 run Hub 链，不起子 run | children 不增 | ✅ 单测 + Runner |
| 8 | 根配额 2 满 → 第三根 429；嵌套子仍可启 | `test_composition_concurrency` | ✅ 单测 |
| 9 | Chat 桥：触发句 → `triggered_run` 回执 | 不走 LLM 长答 | ✅ 脚本 16 |
| 10 | run 终态 → inbox `run_completed`/`run_failed`（含 `conversation_id`） | 44.4 | ✅ `notify_run_terminal` |
| 11 | webhook 无签名 → 401；**签名仅 stub（presence）**，真 HMAC 后置 | `test_channel_inbound` | ✅ stub |

## 金线 8 实测发现(2026-08-15)

**发现 1(产品缺口,记录 education doc):** 教育触发句「帮我生成一份教育热点口播稿」当前规则分类器仅 `conversation 0.6`(< 桥阈值 0.7)——教育意图规则(内容生成/热点)待补,否则教育版旅程 Chat 桥不可触发。

**发现 2(P1,记录 W8 文档):** `match_published_workflow` 不过滤 org(只按 tenant + published)——多组织租户下可能匹配到用户无权访问的 workflow → `start_run` 403 ORG_011 → 桥 fail-soft 降级 LLM。单 org 场景无碍;多 org 需按用户 org 过滤。

**金线 8 已验证的完整旅程:** admin 建/发布父(→子,kind=workflow)+子(挂起能力)workflow → member 起根 run → 子 run 挂起(kb:read)→ 父节点 waiting_child、父仍 running → admin 审批 → 子完成 → **父被唤醒完成** → Chat 高置信触发句(function 1.0)→ `workflow_triggered` 回执。

**复跑:** `APP_ENV=dev LLM_PROVIDER=mock make run` + `uv run python examples/qa/journeys/pilot_b_8_gold_line.py`(需先归档旧 g8-* published workflow,脚本已自动处理)。

## D15 / §6 对照

| 项 | 状态 |
|----|------|
| agent ≠ 子 run；仅 workflow 起子 | ✅ |
| 子挂起 → 父 waiting_child；approve 在子 | ⬜ 金线人工步 |
| 子不占用户根并发槽 | ✅ 单测 |
| composition_depth ≤ 3 + 环检 | ✅ IR + budget |
| 数据流仅 edge/`${input}`/`${output}`；无黑板 | ✅ 40.80 |
| 对外 API 不能伪造 parent_run_id | ✅ |
| fan-out / 总线后置（仅文档） | ✅ composition-runtime §2.3 |
| 租户级熔断（默认 20） | 📄 文档 Should，V1 未实现 |

## 复跑命令

```bash
# API
APP_ENV=dev JWT_SECRET=dev-only-wave-a-jwt-secret-min-32b \
  LLM_PROVIDER=mock \
  uv run python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000

# 单测锚点（金线前置绿）
uv run pytest tests/test_workflow_dataflow.py tests/test_workflow_nesting.py \
  tests/test_agent_chain_in_runner.py tests/test_composition_concurrency.py \
  tests/test_channel_inbound.py tests/test_chat_workflow_bridge.py -q
```

## 禁止项

- 客户端自报 `parent_run_id` 建嵌套  
- agent 暗起子 `workflow_runs`  
- IR 内并行 fan-out（半套执行器）  
- 依赖画布/组合预览 UI（40.83 后置）
