"""Plan 执行快照 API（Task 56 切片 4 · Task 94 S2 语义分离改造）。

Task 94 变更：
- GET snapshot：带 status（streaming/completed/cancelled/failed）；registry 终态窗内
  bus 已释放时由 registry meta 承载 status；租户归属校验；惰性 sweep_expired。
- DELETE /streaming/{trace_id}：幂等 ok（不再对未知/已完成 run 报 404，
  评审 F7：completed 后重复取消不应混淆前端）；bus 存在时仍发 cancelled 事件留痕。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from packages.audit import write_audit_sync
from packages.auth.models import TenantContext
from packages.auth.permissions import require_permission
from packages.plan.event_bus import event_to_dict, get_run_bus_optional
from packages.plan.run_cancel import request_cancel
from packages.plan.run_registry import (
    get_by_trace,
    sweep_expired,
    take_resumed,
)

router = APIRouter(prefix="/api/chat", tags=["chat-execution"])


def _status_for(tenant_id: str, trace_id: str, has_bus: bool) -> str:
    """派生 run 状态：registry entry 优先；仅 bus（legacy/非 chat）时保守 streaming。"""
    entry = get_by_trace(trace_id)
    if entry is not None:
        running = entry.task is None or not entry.task.done()
        if running:
            return "streaming"
        return str(entry.meta.get("status") or "completed")
    if has_bus:
        return "streaming"  # 非 chat registry 管辖（如 workflow bus），无终态信息
    return "not_found"


@router.get("/run/{trace_id}/snapshot")
async def get_run_snapshot(
    trace_id: str,
    request: Request,
    tenant: TenantContext = Depends(require_permission("chat:read")),
):
    """返回 trace 当前执行图快照 + 事件列表 + status（前端刷新/断线恢复分流）。"""
    tid = (trace_id or "").strip()
    if not tid:
        raise HTTPException(status_code=404, detail="run_not_found")

    sweep_expired()
    bus = get_run_bus_optional(tid)
    entry = get_by_trace(tid)
    if entry is None and bus is None:
        # registry 终态窗已过且 bus 已释放：前端降级查历史（按 client_message_id）
        raise HTTPException(status_code=404, detail="run_not_found")
    if entry is not None and entry.tenant_id != tenant.tenant_id:
        # 租户隔离（Task 94 S2）：不泄露他人 run 存在性
        raise HTTPException(status_code=404, detail="run_not_found")

    status = _status_for(tenant.tenant_id, tid, bus is not None)
    # Task 94 S4: 消费者断连后的首个恢复轮询 → chat.resumed 审计（有且仅一次）。
    # 只对仍在跑（streaming）的保温 run 记恢复；终态 run 恢复靠终态文本回填，不记 resumed。
    if (
        status == "streaming"
        and entry is not None
        and take_resumed(tenant.tenant_id, tid)
    ):
        write_audit_sync(
            {
                "tenant_id": tenant.tenant_id,
                "user_id": tenant.user_id,
                "action": "chat.resumed",
                "trace_id": tid,
                "input_text": str(entry.meta.get("message") or "")[:4000],
                "output_text": "client_resumed",
                "model": str(entry.meta.get("model") or ""),
                "ip_address": request.client.host if request.client else "",
                "user_agent": request.headers.get("User-Agent", ""),
                "created_at": datetime.utcnow(),
            }
        )
    if bus is None:
        # 终态查询窗内（bus 已随 producer 完成释放）：status 由 registry 承载
        return {
            "trace_id": tid,
            "status": status,
            "snapshot": {
                "trace_id": tid,
                "goal": "",
                "nodes": [],
                "edges": [],
                "latest_seq": 0,
            },
            "events": [],
            "latest_seq": 0,
        }
    snap = bus.snapshot()
    return {
        "trace_id": tid,
        "status": status,
        "snapshot": snap.to_dict(),
        "events": [event_to_dict(e) for e in bus.events_all()],
        "latest_seq": snap.latest_seq,
    }


@router.delete("/streaming/{trace_id}")
async def cancel_chat_stream(
    trace_id: str,
    request: Request,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """取消进行中的 chat 编排/流式生成（权威信号 = 本端点，Task 94 判定反相）。

    幂等 ok：producer 完成/保温中被二次取消、或 registry 已回收，均不 404——
    取消请求本身无害，审计留痕即可；是否真正中止由 producer 观察取消标志决定。
    """
    tid = (trace_id or "").strip()
    if not tid:
        raise HTTPException(status_code=400, detail="trace_id_required")

    sweep_expired()
    entry = get_by_trace(tid)
    if entry is not None and entry.tenant_id != tenant.tenant_id:
        raise HTTPException(status_code=404, detail="run_not_found")

    meta = entry.meta if entry is not None else {}
    if entry is not None:
        request_cancel(tid)  # producer 每 token/步观察，保温/streaming 均中止
    bus = get_run_bus_optional(tid)
    if bus is not None:
        bus.emit("cancelled", {"reason": "user_request"})
    # Task 94 S4 语义分层: DELETE = 取消请求面审计；真正中止（带已耗量）由 producer
    # 在终态时落 chat.cancelled —— 本行 action 用 cancel_request 避免双计。
    write_audit_sync(
        {
            "tenant_id": tenant.tenant_id,
            "user_id": tenant.user_id,
            "action": "chat.cancel_request",
            "trace_id": tid,
            "input_text": str(meta.get("message") or "")[:4000],
            "output_text": "user_request",
            "model": str(meta.get("model") or ""),
            "error_code": "CHAT_CANCELLED",
            "ip_address": request.client.host if request.client else "",
            "user_agent": request.headers.get("User-Agent", ""),
            "created_at": datetime.utcnow(),
        }
    )
    return {"ok": True, "trace_id": tid, "cancelled": True}
