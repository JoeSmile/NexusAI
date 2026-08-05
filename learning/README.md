# NexusAI — 面试向学习笔记

> 目标：白板讲清 **目标架构**（已签核）+ **代码现状**（诚实债）。  
> 设计权威：[`docs/superpowers/specs/2026-08-05-enterprise-pilot-b-gaps-design.md`](../docs/superpowers/specs/2026-08-05-enterprise-pilot-b-gaps-design.md)（§9–§12）。  
> 原则：**质量与安全优先于工期**；设计未落地处标「目标」，勿讲成已上线。

## 文档地图

| 文件 | 内容 | 类型 |
|------|------|------|
| [00-interview-map.md](00-interview-map.md) | 三维总览 + 双入口白板 + 可讲风险 | 总览 |
| [01-architecture.md](01-architecture.md) | 五层中台全景（对齐试点走向） | 总览 |
| [02-runtime-split.md](02-runtime-split.md) | **人/机分流 · Chat∥Workflow · Runner** | 目标叙事 |
| [03-org-security.md](03-org-security.md) | **组织 B · 平台/业务角色 · S1–S4** | 目标叙事 |
| [04a-auth-rbac.md](04a-auth-rbac.md) | **深挖 A**：现状 Key 认证 + 目标双轨指针 | 代码深挖 |
| [05b-pipeline-nodes.md](05b-pipeline-nodes.md) | **深挖 B**：Chat DAG（仅人侧模糊路径） | 代码深挖 |
| [06-workflow-runner.md](06-workflow-runner.md) | **Workflow Runner · Coze IR · 挂起等批** | 目标叙事 |
| [07c-harness-cost-shortpath.md](07c-harness-cost-shortpath.md) | **深挖 C**：短路径、Harness、成本 | 代码深挖 |
| [08-ux-shells.md](08-ux-shells.md) | **三壳 UX**：`/app` `/admin` `/dev` | 目标叙事 |
| [09d-rag-capability.md](09d-rag-capability.md) | **深挖 D**：RAG vs Hub（Runner 节点） | 代码深挖 |
| [12o-observability.md](12o-observability.md) | 可观测 + 审计字段演进 | 代码深挖 |
| [harness.md](harness.md) | Harness 速记草稿（细节以 07c 为准） | 附录 |

## 建议顺序

```text
00 地图 → 01 全景 → 02 运行时分流 → 03 组织与安全
    → 04a 认证现状/目标 → 06 Runner → 08 UX
    → 05b Chat DAG → 07c 成本 → 09d Hub/RAG → 12o 收尾
```

自测金线（目标态剧本，代码未齐也要能讲）：

```text
组织树 + 经理角色 → 模板表单草稿 → 发布 → 工作台运行
  → 缺权挂起 → dept_manager 批 → resume → auditor 导出
```

对照实现缺口与安全红线：pilot-b **§10–§12**。
