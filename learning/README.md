# NexusAI — 面试向学习笔记

> 更新：2026-08-06。  
> 目标：白板讲清 **目标架构**（已签核）+ **代码现状**（诚实债）。  
> 设计权威：[`docs/superpowers/specs/2026-08-05-enterprise-pilot-b-gaps-design.md`](../docs/superpowers/specs/2026-08-05-enterprise-pilot-b-gaps-design.md)（§9–§12）。  
> 批次计划：[`docs/superpowers/plans/2026-08-05-pilot-b-master-plan.md`](../docs/superpowers/plans/2026-08-05-pilot-b-master-plan.md) · 实现队列：[`tasks/40-pilot-b-chain-a.md`](../tasks/40-pilot-b-chain-a.md)。  
> 原则：**质量与安全优先于工期**；设计未落地处标「目标」，勿讲成已上线。

## 文档地图

| 文件 | 内容 | 类型 |
|------|------|------|
| [00-interview-map.md](00-interview-map.md) | 三维总览 + 双入口白板 + 可讲风险 | 总览 |
| [01-architecture.md](01-architecture.md) | 五层中台全景（对齐试点走向） | 总览 |
| [02-runtime-split.md](02-runtime-split.md) | **人/机分流 · Chat∥Workflow · Plan→IR（D12）** | 目标叙事 |
| [03-org-security.md](03-org-security.md) | **组织 B · 平台/业务角色 · S1–S5** | 目标叙事 |
| [04a-auth-rbac.md](04a-auth-rbac.md) | **深挖 A**：现状 Key 认证 + 目标双轨指针 | 代码深挖 |
| [05b-pipeline-nodes.md](05b-pipeline-nodes.md) | **深挖 B**：Chat DAG（仅人侧模糊路径） | 代码深挖 |
| [06-workflow-runner.md](06-workflow-runner.md) | **Runner · 挂起 · 组合 D14/D15 · Coze IR** | 目标叙事 |
| [07c-harness-cost-shortpath.md](07c-harness-cost-shortpath.md) | **深挖 C**：短路径、Harness、成本 | 代码深挖 |
| [08-ux-shells.md](08-ux-shells.md) | **三壳 UX**：`/app` `/admin` `/dev` · 证据队列 | 目标叙事 |
| [09d-rag-capability.md](09d-rag-capability.md) | **深挖 D**：RAG vs Hub（Runner 节点） | 代码深挖 |
| [12o-observability.md](12o-observability.md) | 可观测 + 审计字段演进 | 代码深挖 |
| [harness.md](harness.md) | Harness 速记草稿（细节以 07c 为准） | 附录 |

## 建议顺序

```text
00 地图 → 01 全景 → 02 运行时分流（含 Plan→IR）→ 03 组织与安全
    → 04a 认证现状/目标 → 06 Runner（含组合 D15）→ 08 UX
    → 05b Chat DAG → 07c 成本 → 09d Hub/RAG → 12o 收尾
```

## 自测金线（目标态 · 代码未齐也要能讲）

**7A 人侧（先会讲这条）：**

```text
组织树 + member/dept_manager → 模板/表单草稿 → 发布
  → 工作台运行（JWT）→ 节点二次鉴权
  → 缺权：保存=可见、运行=可调 → 挂起（D10）
  → dept_manager 批（短命 delegation，D11）→ resume
  → evidence[] / 工作队列「AI 已审」可点开（D13）
  → auditor 导出含 acting_user / credential_kind / run_id
```

**复杂任务（3b，可另讲）：** Chat 不 planner → Plan→IR 草稿 → handoff 卡 → 人确认再跑 Runner（D12）。

**组合（W8，7A 后；面试可一句带过）：**  
仅 `kind=workflow` 起子 run；`kind=agent` 同 run 内 Hub 链、**不**建子 run；子不占用户并发配额（D15）。

对照缺口与红线：pilot-b **§10–§12**；实现 Wave：master **W0→…→7A→W8→2B**。

## 决策速查（面试常问）

| ID | 一句话 | 详文 |
|----|--------|------|
| D10 | 保存=可见 / 运行=可调 → 挂起可达 | master / 03·06 |
| D11 | approve = 短命 delegation，不改长期权限 | 03·06 |
| D12 | Plan 在 Runner/IR；Chat 只 handoff | [02](02-runtime-split.md) · [plan-process](../docs/superpowers/plans/2026-08-05-pilot-b-plan-process.md) |
| D13 | evidence + 审批队列体验（学 AtlasClaw UX） | 08·06 |
| D14/D15 | 组合=人侧核心；agent **先不建**子 run | [06](06-workflow-runner.md) · [composition-runtime](../docs/superpowers/plans/2026-08-05-pilot-b-composition-runtime.md) |
| D16 | 流程 `V1.0.0` + `revision` INT；审计两者都写；发布只涨 revision | [lifecycle](../docs/superpowers/designs/2026-08-05-lifecycle-versioning.md) |

## 相关设计（非 learning，备忘）

| 文档 | 用途 |
|------|------|
| [pilot-b spec](../docs/superpowers/specs/2026-08-05-enterprise-pilot-b-gaps-design.md) | 事实源 §9–§12 |
| [master plan](../docs/superpowers/plans/2026-08-05-pilot-b-master-plan.md) | Wave / D* 闸 |
| [composition-runtime](../docs/superpowers/plans/2026-08-05-pilot-b-composition-runtime.md) | 多 workflow/agent · 并发 · 扩展 |
| [concurrency](../docs/superpowers/plans/2026-08-05-pilot-b-concurrency.md) | CAS / 幂等 / 用户并发槽 |
| [plan-process](../docs/superpowers/plans/2026-08-05-pilot-b-plan-process.md) | Plan→IR |
| [Task 40](../tasks/40-pilot-b-chain-a.md) | 链 A 实现切片 |
