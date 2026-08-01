# Task 03: 多租户隔离 + 审计日志

> ⚠️ 审计日志写入必须是 **fire-and-forget**（`BackgroundTasks`），不 block 主请求。
> **前置依赖:** `tasks/02-auth-rbac.md`（需要 TenantContext）
> **完成后:** 执行 `tasks/04-langgraph-pipeline.md`
> 审计存 **原始输入**（脱敏前），不是脱敏后。

## Subtask 03.01: 租户中间件

**文件:** `backend/core/tenant.py`
- FastAPI middleware 注入 `request.state.trace_id` (`tr_{uuid.hex[:12]}`)
- 从 `TenantContext` 提取 tenant_id

## Subtask 03.02: 审计日志写入

**文件:** `backend/core/audit.py`
```python
def log_audit(
    background_tasks: BackgroundTasks,
    tenant_id: str, user_id: str, action: str, trace_id: str,
    input_text: str, output_text: str,
    model: str = "", input_tokens: int = 0, output_tokens: int = 0,
    cost: float = 0.0, latency_ms: float = 0.0,
    error_code: str | None = None, ip_address: str = "", user_agent: str = "",
):
    record = {...}  # 完整审计记录
    background_tasks.add_task(_write_audit, record)

async def _write_audit(record: dict):
    """后台写入 audit_logs 表"""
```

## Subtask 03.03: 审计导出 API

**文件:** `backend/routers/audit.py`
- `GET /audit/logs` — 按 tenant/时间范围查询
- `GET /audit/export` — 导出 CSV
- 只有 `cross_tenant_only` 角色能访问

## Subtask 03.04: ORM 数据隔离

- `PGVectorSession` 加 `query_with_tenant()` 方法
- 所有 `ChatMessage` 查询自动 `WHERE tenant_id=:tid AND user_id=:uid`

## 验证

- 租户 A 查不到租户 B 的数据
- user 只能看自己的对话
- auditor 跨租户看审计日志，但看不到对话内容
