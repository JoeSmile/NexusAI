"""Task 94 S1 — 进程级 run 注册表（tenant 维度 / 取消入口 / TTL sweep）单测。

覆盖：
- register/get/unregister
- tenant 隔离：同 trace_id 不同 tenant 互不覆盖
- cancel 委托 run_cancel 置标志（编排检查点零改动消费）
- cancel 幂等 / 未注册返回 False
- sweep 纯函数 + 注入时钟：
  - 超 TTL 且 task 已完成 → 清理
  - 超 TTL 但 task 仍在跑 → 保留（D6 语义 a：GC 永不砍在跑 producer）
  - 未超 TTL → 保留；重复 sweep 幂等
"""

from __future__ import annotations

from packages.plan import run_cancel
from packages.plan.run_registry import (
    active_count,
    cancel,
    get,
    mark_consumer_lost,
    register,
    sweep,
    take_resumed,
    unregister,
)


class _FakeTask:
    """sweep 只检查 task.done()——同步测试不需要真事件循环。"""

    def __init__(self, done: bool) -> None:
        self._done = done

    def done(self) -> bool:
        return self._done


def test_register_get_unregister():
    entry = register("t1", "trace-1", ttl_s=60)
    assert get("t1", "trace-1") is entry
    assert get("t1", "trace-1").deadline is not None
    unregister("t1", "trace-1")
    assert get("t1", "trace-1") is None


def test_tenant_isolation():
    register("t1", "same-trace")
    register("t2", "same-trace")
    assert active_count() == 2
    unregister("t1", "same-trace")
    assert get("t2", "same-trace") is not None
    assert get("t1", "same-trace") is None


def test_cancel_sets_run_cancel_flag_and_idempotent():
    run_cancel.clear_cancel("trace-c")
    register("t1", "trace-c")
    assert cancel("t1", "trace-c") is True
    assert run_cancel.is_cancelled("trace-c") is True
    # 幂等
    assert cancel("t1", "trace-c") is True
    # 未注册
    assert cancel("t1", "no-such") is False


def test_cancel_requires_tenant_match():
    run_cancel.clear_cancel("trace-t")
    register("t1", "trace-t")
    assert cancel("t2", "trace-t") is False
    assert run_cancel.is_cancelled("trace-t") is False


def test_consumer_lost_mark_and_take_resumed_once():
    """Task 94 S4: 断连标记只能被 resumed 消费一次；无 entry 均为 False。"""
    run_cancel.clear_cancel("trace-cl")
    register("t1", "trace-cl", task=_FakeTask(done=False))
    try:
        assert take_resumed("t1", "trace-cl") is False  # 未断连无标记
        assert mark_consumer_lost("t1", "trace-cl") is True
        assert mark_consumer_lost("t1", "trace-cl") is True  # 幂等置位
        assert take_resumed("t1", "trace-cl") is True  # 首个恢复轮询消费
        assert take_resumed("t1", "trace-cl") is False  # 有且仅一次
        assert mark_consumer_lost("t1", "no-such-trace") is False
        assert take_resumed("t1", "no-such-trace") is False
        # 异租户不可见
        assert mark_consumer_lost("t2", "trace-cl") is False
        assert take_resumed("t2", "trace-cl") is False
    finally:
        unregister("t1", "trace-cl")


def test_sweep_removes_expired_done_task():
    import time as _t

    task = _FakeTask(done=True)
    register("t1", "expired-done", task=task, ttl_s=1)
    now = _t.monotonic() + 10
    assert sweep(now=now) == ["expired-done"]
    assert get("t1", "expired-done") is None


def test_sweep_keeps_running_task_over_ttl():
    """D6a：TTL 只关保温等待窗，永不砍仍在跑的 producer。"""
    import time as _t

    running = _FakeTask(done=False)
    register("t1", "running-long", task=running, ttl_s=1)
    now = _t.monotonic() + 10
    assert sweep(now=now) == []
    assert get("t1", "running-long") is not None


def test_sweep_keeps_not_expired():
    import time as _t

    register("t1", "fresh", ttl_s=3600)
    now = _t.monotonic() + 1
    assert sweep(now=now) == []
    assert get("t1", "fresh") is not None


def test_sweep_idempotent_and_skips_no_deadline():
    import time as _t

    register("t1", "no-deadline")
    register("t1", "expired", ttl_s=1)
    now = _t.monotonic() + 10
    assert sweep(now=now) == ["expired"]
    assert sweep(now=now) == []
    assert get("t1", "no-deadline") is not None
