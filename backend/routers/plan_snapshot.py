"""Plan 执行快照 API（Task 56 切片 4）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.core.auth.models import TenantContext
from backend.core.auth.permissions import require_permission
from backend.core.plan.event_bus import event_to_dict, get_run_bus_optional

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
