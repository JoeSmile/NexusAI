# QA — Admin 管理

> 来源: `docs/MANUAL_TEST.md` §8。一键脚本: `./examples/qa/08-admin/admin_qa.sh`
> 需 super_admin key(8.1-8.4);8.5 审批流需 user + tenant_admin/super 各一把。

## 用例

| # | 验证点 | 操作 | 预期 |
|---|--------|------|------|
| 8.1 | api-keys 创建 | `POST /api/admin/api-keys` {user_id,role,tenant_id} | 返回新 key(只显示一次) |
| 8.2 | api-keys 删除 | 删刚建的 key | 删除后用该 key 请求 → 401 |
| 8.3 | llm-keys 加密入库 | `POST /api/admin/llm-keys` {key_alias,api_key_plaintext} | 落库为密文,列表不显示明文 |
| 8.4 | llm-keys verify | `POST /api/admin/llm-keys/{id}/verify` | 返回连通性结果 |
| 8.5 | 审批流 | user 调 `POST /api/admin/permissions/request` → pending-requests → approve | request → pending → approved |
| 8.6 | audit 导出 | `GET /api/audit/export` | CSV/JSON 导出成功 |

## 一键

```bash
QA_USER_KEY=<user> QA_SUPER_KEY=<super_admin> ./examples/qa/08-admin/admin_qa.sh
```
