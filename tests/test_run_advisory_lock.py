"""Task 73 slice 5 — execute_run advisory lock 防多 worker 双跑。

崩溃后 PG 会话结束会自动释放 session-level advisory lock，另一实例可
pg_try_advisory_lock + CAS pending→running 接手（或把陈旧 running 标失败，见 hang 扫描）。
"""

from __future__ import annotations

import pytest

from packages.workflow.run_lifecycle import execute_run, run_advisory_lock_key


def test_run_advisory_lock_key_stable_and_positive() -> None:
    a = run_advisory_lock_key("run-aaa")
    b = run_advisory_lock_key("run-aaa")
    c = run_advisory_lock_key("run-bbb")
    assert a == b
    assert a != c
    assert 0 < a <= 0x7FFFFFFFFFFFFFFF


class _LockBusySession:
    def query(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("must not query when advisory lock is busy")

    def execute(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("must not CAS when advisory lock is busy")

    def close(self) -> None:
        return None

    def __enter__(self) -> _LockBusySession:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class _LockBusyFactory:
    def Session(self) -> _LockBusySession:
        return _LockBusySession()


@pytest.mark.asyncio
async def test_busy_advisory_lock_skips_without_cas(monkeypatch: pytest.MonkeyPatch) -> None:
    """拿不到锁 → 不执行 CAS（另一 worker 正在跑）。"""
    monkeypatch.setattr(
        "packages.workflow.run_lifecycle.get_pg_session",
        lambda: _LockBusyFactory(),
    )
    monkeypatch.setattr(
        "packages.workflow.run_lifecycle._try_execute_lock",
        lambda session, run_id: False,
    )
    await execute_run("run-held-elsewhere")
