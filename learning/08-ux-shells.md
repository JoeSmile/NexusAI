# 08 — 前端三壳 UX（目标态）

> 更新：2026-08-05。设计：[pilot-b §12](../docs/superpowers/specs/2026-08-05-enterprise-pilot-b-gaps-design.md)。  
> **代码现状：** `frontend/` 是 **QA 测试控制台**（多面板 + 四槽 API Key），不是 `/app` `/admin` 产品壳。

---

## 一句话

**同仓一个 Vite App，三套信息架构：** 业务工作台 · 管理台 · 开发面板；登录 JWT；按 `platform_role` 默认落地。

---

## 路由

```text
/login · /register  → JWT（目标；现状仍发 cg_）
/app/*   业务壳（默认 user）
/admin/* 管理壳（默认 tenant_admin / auditor / super_admin）
/dev/*   现有 QA 面板（journeys / 安全负向）
```

| 角色 | 默认 | 也可 |
|------|------|------|
| user | `/app` | Chat 二级 |
| tenant_admin | `/admin` | `/app`（全套测流） |
| auditor | `/admin` 审计向 | 导出 |
| super_admin | `/admin` | `/dev` 可选 |

产品壳 **不用** 四槽 API Key；`/dev` 可保留角色切换。

---

## 编排交互上限

| 壳 | 第一期 | 后置 |
|----|--------|------|
| `/app` 我的流程 | **模板 + 表单**（选模板、填参、排序） | — |
| `/admin` 流程 | **步骤列表 + 只读预览图** | 受限拖拽画布 |
| Chat | 试点 **二级** | 后期「办公桌面」卡片 → 仍调 Runner |

节点选择器只列 **OrgScope + 权限内** capability；保存服务端再校验。

---

## `/app` 关键页

工作台（大按钮样板 / 待办 / 最近运行）· 我的流程 · 运行与历史 · 待办（待我批 vs 我发起的挂起）· Chat  

## `/admin` 关键页

概览（待批、失败 run、越权拒绝）· **组织**（树/兼岗/业务角色）· 流程 · Coze 导入 · 权限/挂起 · 审计 · 集成 Key · 模型  

---

## 好用原则（摘要）

一屏一主任务 · 空态/错误可行动 · 挂起写清等谁 · 文案不泄露他租户/部门探测信息 · OrgScope 参数不可客户端扩权  

金线与 Runner → [06](06-workflow-runner.md)。组织 → [03](03-org-security.md)。
