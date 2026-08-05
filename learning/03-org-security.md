# 03 — 组织 B 与安全红线

> 更新：2026-08-05。设计：[pilot-b §11](../docs/superpowers/specs/2026-08-05-enterprise-pilot-b-gaps-design.md) · 安全：[§10 S1–S4](../docs/superpowers/specs/2026-08-05-enterprise-pilot-b-gaps-design.md)。  
> **代码现状：** 仅四平台角色 + `user_app_perms`；**无**部门树 / 业务角色 / `OrgScope`。  
> 原则：**质量与安全优先于工期**——组织按 B 档设计，不先做扁平凑合。

---

## 一句话

**平台角色管壳与治理；业务角色管部门职责与审批路由；所有过滤走唯一 `OrgScope`。**

---

## 两套角色（勿混）

| 种类 | 管什么 | 例子 |
|------|--------|------|
| `platform_role` | `/app` vs `/admin`、治理权限包 | `user` / `tenant_admin` / `auditor` / `super_admin` |
| `business_role` | 部门内谁能批、数据范围 | `member` / `dept_manager` / `dept_operator` … |

例：`platform_role=user` + `dept_manager@财务部` → 默认工作台，可批本部门挂起。  
**禁止**用「人人升 tenant_admin」模拟经理。

现状四角色深挖 → [04a](04a-auth-rbac.md)。

---

## 组织对象（目标）

```text
tenant
  └── org_unit（树：parent_id + path）
        └── membership（user ↔ org_unit，is_primary，business_roles[]）

user（display_name，employee_no，…）
```

- 兼职多部门；**主部门**用于顶栏与默认审批路由。  
- 列表 / Runner / 出站：**只**经 `OrgScope`；禁止散落 `department_id ==`，禁止客户端自报部门扩权。

---

## 权限叠加

```text
放行 =
  平台权限包
  ∪ extra_permissions（显式加挂，须审计）
  ∪ 业务角色权限（仅其 org_scope 内）

且必须满足 OrgScope（租户 → 子树 → 行级）
```

挂起路由：本部门业务角色（如 `dept_manager`）→ 找不到则升级 `tenant_admin` 并审计原因。

---

## 安全红线 S1–S4（一票否决）

| ID | 红线 | 必须 |
|----|------|------|
| **S1** | 申请不可伪造 | 身份只来自已校验会话；禁客户端乱填 `acting_user`；approve 角色受限；进审计 |
| **S2** | 挂起≠提权后门 | 仅 `requestable`；跨租户/密钥/连接器写 **不可申请**；增量可收回 |
| **S3** | 数据隔离 | `tenant_id` + `OrgScope`；跨部门默认拒绝 |
| **S4** | 票不绕人 | delegation / machine key 不能绕过 acting_user；浏览器无连接器密钥/delegation |

**红线未满足：不上挂起等批，无权节点直接失败。**

---

## 面试追问

1. `user` 和「财务经理」是一回事吗？→ 不是；平台角色 vs 业务角色。  
2. 子部门数据上级能否看？→ 由 `OrgScope`/显式授权决定，默认安全侧拒绝要能说清。  
3. 有 delegation 就能调 OA？→ 否；二次鉴权 + OrgScope + S4。  

UX 里组织怎么露 → [08](08-ux-shells.md)。Runner 里怎么挂起 → [06](06-workflow-runner.md)。
