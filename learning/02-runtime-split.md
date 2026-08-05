# 02 — 运行时分流：人 / 机 · Chat ∥ Workflow

> 更新：2026-08-05。设计：[pilot-b §9](../docs/superpowers/specs/2026-08-05-enterprise-pilot-b-gaps-design.md) · 白板：[00](00-interview-map.md)。  
> **代码现状：** 仍是单 `X-API-Key`，无独立 Workflow Runner——面试必须区分目标/现状。

---

## 一句话

**模糊需求走 Chat 管线；确定动作走 Workflow Runner。**  
人用 JWT；机器用 machine API Key；机器 **永不** 进 Chat DAG。

---

## 双入口

| | 人 | 机 |
|--|----|----|
| 凭证 | JWT · `Authorization: Bearer` | `X-API-Key`（`credential_type=machine`） |
| Depends（目标） | `verify_session` | `verify_api_key`（拒非 machine） |
| 可去 | Chat **或** 工作台「运行」 | **仅** Workflow run / 定时 / webhook |
| 禁止 | 浏览器长期持 `cg_` | 把 Key 当 Chat 会话 |

下游统一：`TenantContext` + `credential_kind` + `acting_user_id`。

---

## 模糊 vs 确定

| | 模糊 | 确定 |
|--|------|------|
| 例子 | 「看看报销有没有异常」 | 「运行《月度对账》」「批准请假」 |
| 入口 | Chat / SSE | 工作台按钮、编排「运行」、机侧 run API |
| 执行 | LangGraph Chat DAG | **Workflow Runner** |
| 成本 | 可能走 LLM | 按节点；可 $0 工具节点 |

**「确定动作不进 Chat」** = 执行不进 Chat **管线**；不是禁止以后在 Chat **UI** 里点卡片——后期 Chat 办公桌面点卡仍调 Runner（见 [08](08-ux-shells.md)）。

---

## 目标白板

```text
人 JWT ──┬── Chat DAG（05b）── short skill / long Harness
         └── 「运行」────────┐
机 Key ─────────────────────┤
                            ▼
                   Workflow Runner（06）
                   · IR：自研 / Coze 导入 / 后期画布
                   · 节点 = capability（09d）
                   · 二次鉴权 + OrgScope（03）
                   · 可申请 → 挂起等批（先过 S1–S4）
                            ▼
                   audit + LangFuse（12o）
```

---

## Chat 两阶段（产品）

| 阶段 | Chat 角色 |
|------|-----------|
| **试点** | `/app` **二级**；主入口是工作台 |
| **后期** | 升「办公桌面」（总结卡/审批卡/对话触发已发布链）；执行仍 Runner |

---

## 面试追问

1. 机器打 `/chat` 对吗？→ 目标不对；应打 workflow run。  
2. 人为何不用长期 Key？→ 短会话可吊销；Key 给集成。  
3. 后期 Chat 里批请假是否违反分流？→ 否；UI 在 Chat，执行在 Runner。  

现状债与迁移：pilot-b §9.6（M1–M6）。
