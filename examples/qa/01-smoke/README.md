# QA — 冒烟(系统存活)

> 来源: `docs/MANUAL_TEST.md` §1。一键脚本: `./examples/qa/01-smoke/smoke_qa.sh`

## 用例

| # | 验证点 | 操作 | 预期 |
|---|--------|------|------|
| 1.1 | 根路径 | `GET /` | name=ContextGate,status=running,features 非空 |
| 1.2 | 健康检查 | `GET /health` | db/pgvector/langfuse 三项 healthy(含 cache=redis) |
| 1.3 | 系统信息 | `GET /system/info` | 架构信息,router 列表含 chat/memory/evaluation |
| 1.4 | 无 key 拒绝 | `POST /chat` 不带 key | 401 `AUTH_001 missing_api_key` |
| 1.5 | 权限首查 | user key 打 `GET /api/admin/api-keys` | 403;super_admin key → 200 |

## 一键

```bash
QA_USER_KEY=<user key> QA_SUPER_KEY=<super_admin key> ./examples/qa/01-smoke/smoke_qa.sh
```
