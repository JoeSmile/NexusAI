# QA — 认证与权限矩阵

> 来源: `docs/MANUAL_TEST.md` §2。一键脚本: `./examples/qa/02-auth/auth_matrix_qa.sh`
> 需 4 种角色 key(seed 或 admin 创建);缺失的 key 对应用例自动跳过。

## 矩阵(2026-08-02 实测修正版)

| 端点 | user | tenant_admin | auditor | super_admin |
|------|------|--------------|---------|-------------|
| `POST /chat`(chat:write) | ✓ 200 | ✓ 200 | ✗ 403 | ✓ 200 |
| `GET /api/admin/api-keys`(admin:*) | ✗ 403 | ✗ 403 | ✗ 403 | ✓ 200 |
| `POST /api/admin/approve`(admin:approve) | ✗ 403 | ✓ 非403 | ✗ 403 | ✓ 非403 |
| `GET /api/audit/logs`(audit:read) | ✗ 403 | ✗ 403 | ✓ 200 | ✓ 200 |
| `GET /api/audit/export`(audit:export) | ✗ 403 | ✗ 403 | ✓ 200 | ✓ 200 |

> 通过标准: 无越权;auditor 只能读审计,不能写。tenant_admin 无 admin:* 也无 audit:read(设计如此)。

## 一键

```bash
QA_USER_KEY=<user> QA_TADMIN_KEY=<tenant_admin> QA_AUDITOR_KEY=<auditor> \
QA_SUPER_KEY=<super_admin> ./examples/qa/02-auth/auth_matrix_qa.sh
```
