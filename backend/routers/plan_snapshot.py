"""Plan 执行快照 API（Task 56 切片 4）。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.core.audit import write_audit_sync
from packages.auth.models import TenantContext
from packages.auth.permissions import require_permission
from backend.core.plan.event_bus import event_to_dict, get_run_bus_optional
from backend.core.plan.run_cancel import request_cancel

router = APIRouter(prefix="/api/chat", tags=["chat-execution"])


@router.get("/run/{trace_id}/snapshot")
async def get_run_snapshot(
    trace_id: str,
    tenant: TenantContext = Depends(require_permission("chat:read")),
):
    """返回 trace 当前执行图快照 + 事件列表（前端刷新可恢复）。"""
    _ = tenant
    bus = get_run_bus_optional(trace_id)
    if bus is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    snap = bus.snapshot()
    return {
        "trace_id": trace_id,
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
    """显式取消进行中的 chat 编排/流式生成（Task 63 slice 3）。"""
    tid = (trace_id or "").strip()
    if not tid:
        raise HTTPException(status_code=400, detail="trace_id_required")
    if not request_cancel(tid) and get_run_bus_optional(tid) is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    bus = get_run_bus_optional(tid)
    if bus is not None:
        bus.emit("cancelled", {"reason": "user_request"})
    write_audit_sync(
        {
            "tenant_id": tenant.tenant_id,
            "user_id": tenant.user_id,
            "action": "chat.cancelled",
            "trace_id": tid,
            "input_text": "",
            "output_text": "user_request",
            "error_code": "CHAT_CANCELLED",
            "ip_address": request.client.host if request.client else "",
            "user_agent": request.headers.get("User-Agent", ""),
            "created_at": datetime.utcnow(),
        }
    )
    return {"ok": True, "trace_id": tid, "cancelled": True}
