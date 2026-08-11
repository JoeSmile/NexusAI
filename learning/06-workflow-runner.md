# 06 — Workflow Runner（目标态）

> 更新：2026-08-05。设计：pilot-b J1/J2 · §9.4–9.5 · §10 T1/T3/T5/T7。  
> **代码现状：** Hub `invoke` + Agent 链雏形；**无一等公民 Runner / run 状态机 / 挂起 resume**。

---

## 一句话

**Runner = 确定动作的唯一执行面。**  
编排来源（自研表单 / Coze 导入 / 后期画布）只影响 IR；执行、护栏、鉴权、审计不换引擎。

---

## 在架构里的位置

```text
工作台「运行」 / 机侧 run API / 后期 Chat 卡片
                    │
                    ▼
            Workflow Runner
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
   capability   二次鉴权     出站连接器
   节点(09d)   +OrgScope(03)  machine key
        │           │           │
        └───────────┴───────────┘
                    │
              挂起 / resume / 失败
                    ▼
              audit + LangFuse（run_id）
```

Chat DAG（[05b](05b-pipeline-nodes.md)）**并行存在**，只服务人侧模糊对话——不是 Runner 的替代品。

---

## 组合（多 Workflow / 多 Agent · 目标态）

> 设计全文：[`docs/superpowers/plans/2026-08-05-pilot-b-composition-runtime.md`](../docs/superpowers/plans/2026-08-05-pilot-b-composition-runtime.md)（D14/D15）。实现 Wave 8。

| 关系 | 形态 |
|------|------|
| 并列 | 多个根 run（每用户 running 根 ≤2） |
| 嵌套 | `kind=workflow` → 子 run + `parent_run_id`；父节点 `waiting_child` |
| Agent | `kind=agent` → **同 run** 内 Hub 链；**不起**子 run |
| 通信 | 同 run：`edges` + `${output…}`；父子：input_bindings + 子终态汇总 |
| 防爆 | 环检测 + `composition_depth≤3`；子不占额外并发槽 |

**现状：** Hub 有 agent 链雏形；Runner/嵌套未建——面试区分目标/现状。

---

## 最小能力（试点 Must）

| 能力 | 说明 |
|------|------|
| IR | 有序节点 = 已授权 capability + 参数 + 版本 |
| Run 状态机 | running / succeeded / failed / **suspended** |
| 历史 | 按 OrgScope 列表；节点日志可见 |
| 二次鉴权 | 每节点相对 `acting_user`；delegation 的 `caps` 只是上限 |
| 挂起等批 | 可申请且过 **S1–S4** → suspended → 业务角色/admin 批 → resume；请假等 HITL 见 [human-gate 设计](../docs/superpowers/designs/2026-08-08-human-gate-hitl.md) |
| 护栏 | LLM/外发必须过治理入口（Harness/guardrails），禁裸 SDK（T5） |
| Coze A | 导入→校验→映射本租户能力；不支持则整单拒或标红不可发布（写死一种） |

---

## 与 Hub 的关系

| Hub 今天 | Runner 目标 |
|----------|-------------|
| 注册表 + 单次 `invoke` | 多节点编排执行 + 状态 + 历史 |
| 动态 `spec.permission` | 保留，并叠加 OrgScope + 挂起 |
| Agent 链雏形 | 收敛进同一 IR/Runner 叙事，避免双轨 |

深挖 Hub 代码 → [09d](09d-rag-capability.md)。

---

## 金线剧本（测得见）

```text
admin 建组织与 dept_manager
  → user 模板+表单存部门草稿 → admin 发布
  → user 工作台运行 → 节点缺权挂起
  → 经理待办批准 → resume 完成
  → auditor 导出（acting_user / org / credential_kind / run_id）
```

UX 页面 → [08](08-ux-shells.md)。安全 → [03](03-org-security.md)。
