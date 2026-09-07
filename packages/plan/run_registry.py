"""进程级 run 注册表 — (tenant_id, trace_id) → RunEntry（Task 94）。

统一管理 chat 流式长路径的 producer 生命周期：
- producer task 强引用（防 GC / 脱离请求 cancel scope）
- 保温 deadline 与 GC（sweep 纯函数，注入时钟可测）
- 取消入口（委托 run_cancel 置标志，编排现有 check_cancelled 零改动）
- 单 worker 部署假设（D9）；多副本 = Redis 化前置门禁

与既有模块的关系：
- run_cancel.py 继续管「取消标志」（orchestrator 检查点读它），本模块的 cancel() 是带租户校验的入口
- event_bus.py 继续管事件，本模块可持有 bus 引用统一注销
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from packages.plan.event_bus import PlanEventBus

_lock = threading.Lock()
_runs: dict[tuple[str, str], RunEntry] = {}


@dataclass
class RunEntry:
    tenant_id: str
    trace_id: str
    task: asyncio.Task[Any] | None = None
    bus: PlanEventBus | None = None
    created_at: float = field(default_factory=time.monotonic)
    # 保温等待窗 deadline（monotonic）；None = 不限（如 producer 已在跑，不设等待窗）
    deadline: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    # Task 94 S4: 消费者断连退场标记；首个恢复轮询落 chat.resumed 审计后清除
    consumer_lost: bool = False


def _key(tenant_id: str, trace_id: str) -> tuple[str, str]:
    return (str(tenant_id or "").strip(), str(trace_id or "").strip())


def register(
    tenant_id: str,
    trace_id: str,
    *,
    task: asyncio.Task[Any] | None = None,
    bus: PlanEventBus | None = None,
    ttl_s: float | None = None,
    meta: dict[str, Any] | None = None,
) -> RunEntry:
    """注册一个 run。ttl_s > 0 时记保温等待窗 deadline（sweep 用）。"""
    entry = RunEntry(
        tenant_id=str(tenant_id or "").strip(),
        trace_id=str(trace_id or "").strip(),
        task=task,
        bus=bus,
        meta=dict(meta or {}),
        deadline=(time.monotonic() + float(ttl_s)) if ttl_s else None,
    )
    from packages.plan.run_cancel import register_run

    register_run(entry.trace_id)  # 取消标志侧登记（编排 check_cancelled 依赖 _active）
    with _lock:
        _runs[_key(entry.tenant_id, entry.trace_id)] = entry
    return entry


def get(tenant_id: str, trace_id: str) -> RunEntry | None:
    with _lock:
        return _runs.get(_key(tenant_id, trace_id))


def get_by_trace(trace_id: str) -> RunEntry | None:
    """按 trace_id 查（不限租户）——端点租户校验用：先定位再比 tenant。"""
    tid = str(trace_id or "").strip()
    if not tid:
        return None
    with _lock:
        for (_, t), entry in _runs.items():
            if t == tid:
                return entry
    return None


def unregister(tenant_id: str, trace_id: str) -> None:
    from packages.plan.run_cancel import clear_cancel, unregister_run

    key = _key(tenant_id, trace_id)
    with _lock:
        _runs.pop(key, None)
    # 取消标志侧同步注销（unregister 移到 producer 完成后，见 plan D2）
    unregister_run(trace_id)
    clear_cancel(trace_id)


def cancel(tenant_id: str, trace_id: str) -> bool:
    """租户校验的取消入口：置 run_cancel 标志（编排检查点据此中止）。

    返回 False = 该 (tenant, trace) 不在注册表（调用方按 404 处理）。
    幂等：重复 cancel 返回 True。
    """
    entry = get(tenant_id, trace_id)
    if entry is None:
        return False
    from packages.plan.run_cancel import request_cancel

    request_cancel(entry.trace_id)
    return True


def finish(
    tenant_id: str,
    trace_id: str,
    status: str,
    *,
    keep_s: float = 60.0,
) -> None:
    """producer 终态标记（Task 94 S2）。

    entry 保留 keep_s 供 snapshot 查询终态（bus 已释放，status 由 meta 承载）；
    保留期过后由 sweep_expired() 惰性清理。run_cancel 同步注销
    （producer 已完成，取消标志无意义）。
    """
    from packages.plan.run_cancel import clear_cancel, unregister_run

    key = _key(tenant_id, trace_id)
    with _lock:
        entry = _runs.get(key)
        if entry is not None:
            entry.meta["status"] = status
            entry.deadline = time.monotonic() + max(0.0, float(keep_s))
    unregister_run(trace_id)
    clear_cancel(trace_id)


def mark_consumer_lost(tenant_id: str, trace_id: str) -> bool:
    """标记消费者已断连退场（保温中；供 snapshot GET 判定是否需要 resumed 审计）。"""
    key = _key(tenant_id, trace_id)
    with _lock:
        entry = _runs.get(key)
        if entry is None:
            return False
        entry.consumer_lost = True
        return True


def take_resumed(tenant_id: str, trace_id: str) -> bool:
    """取走 resumed 标记（有且仅一次）；无 entry 或无标记返回 False。"""
    key = _key(tenant_id, trace_id)
    with _lock:
        entry = _runs.get(key)
        if entry is None:
            return False
        flag = entry.consumer_lost
        entry.consumer_lost = False
        return flag


def sweep_expired(now: float | None = None) -> list[str]:
    """惰性 GC：清理已过 deadline 且 task 已完成/无 task 的终态 entry。

    与 sweep() 的差异：sweep_expired 清理的是 finish() 保留的终态查询窗
    （超窗说明前端已过恢复期，可释放）；仍在跑的任务永不清理。
    供 snapshot/cancel 端点惰性调用（无后台线程）。
    """
    now = time.monotonic() if now is None else float(now)
    reaped: list[str] = []
    with _lock:
        for (tenant_id, trace_id), entry in list(_runs.items()):
            if entry.deadline is None or entry.deadline > now:
                continue
            if entry.task is not None and not entry.task.done():
                continue
            _runs.pop((tenant_id, trace_id), None)
            reaped.append(trace_id)
    return reaped


def active_count() -> int:
    with _lock:
        return len(_runs)


def list_runs() -> list[RunEntry]:
    with _lock:
        return list(_runs.values())


def sweep(now: float | None = None) -> list[str]:
    """GC 纯函数（可注入时钟）：清理「超 TTL 且 task 已完成/无 task」的泄漏项。

    D6 语义 a：**永不清理仍在跑的 producer**——挂死由 producer 请求级超时兜底，
    不在 GC 砍 LLM 连接。返回被清理的 trace_id 列表。
    """
    now = time.monotonic() if now is None else float(now)
    reaped: list[str] = []
    with _lock:
        for (tenant_id, trace_id), entry in list(_runs.items()):
            if entry.deadline is None or entry.deadline > now:
                continue
            if entry.task is not None and not entry.task.done():
                # 仍在跑的 producer：TTL 只关保温等待窗，不砍任务
                continue
            _runs.pop((tenant_id, trace_id), None)
            reaped.append(trace_id)
    from packages.plan.run_cancel import clear_cancel, unregister_run

    for tid in reaped:
        unregister_run(tid)
        clear_cancel(tid)
    return reaped
