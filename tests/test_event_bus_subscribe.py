"""Task 94 S1 — PlanEventBus 订阅能力（wait_next / gap 标记）单测。

覆盖：
- emit seq 单调
- wait_next 返回 seq>last 的新事件（含注册竞态：emit 在注册前后均不漏不重）
- wait_next 超时返回 []
- wait_next 在 last_seq 已被淘汰（空洞）时抛 BusGapError
- dropped_upto 记录有界队列淘汰断点
"""

from __future__ import annotations

import asyncio

import pytest

from packages.plan.event_bus import BusGapError, PlanEventBus


def _bus(max_events: int = 2048) -> PlanEventBus:
    return PlanEventBus("t-trace-1", max_events=max_events)


def test_emit_seq_monotonic():
    bus = _bus()
    seqs = [bus.emit("tool_call", {"step_id": f"s{i}"}).seq for i in range(5)]
    assert seqs == [1, 2, 3, 4, 5]
    assert bus.latest_seq() == 5


@pytest.mark.asyncio
async def test_wait_next_returns_events_after_seq():
    bus = _bus()
    bus.emit("plan", {"goal": "g"})
    bus.emit("step", {"id": "s1", "status": "running"})

    events = await bus.wait_next(1)
    assert [e.seq for e in events] == [2]
    assert events[0].type == "step"

    # 无新事件时阻塞到超时 → []
    events = await bus.wait_next(2, timeout=0.05)
    assert events == []


@pytest.mark.asyncio
async def test_wait_next_consumer_producer_no_gap_no_dup():
    """并发生产者 emit / 消费者 wait_next 循环：seq 连续无重复无空洞。"""
    bus = _bus()
    total = 100

    async def produce():
        for i in range(total):
            bus.emit("step", {"id": f"s{i}", "status": "done"})
            await asyncio.sleep(0)  # 让出循环，增加交错机会

    async def consume():
        seen: list[int] = []
        last = 0
        deadline = asyncio.get_event_loop().time() + 5
        while len(seen) < total:
            if asyncio.get_event_loop().time() > deadline:
                raise AssertionError("consumer timeout")
            events = await bus.wait_next(last, timeout=0.5)
            for e in events:
                assert e.seq == last + 1, f"gap/dup at {e.seq}, last={last}"
                seen.append(e.seq)
                last = e.seq
        return seen

    producer_task = asyncio.create_task(produce())
    seen = await consume()
    await producer_task
    assert seen == list(range(1, total + 1))


@pytest.mark.asyncio
async def test_wait_next_two_consumers_independent():
    """双消费者各持 lastSeq，互不干扰。"""
    bus = _bus()
    bus.emit("plan", {"goal": "g"})

    async def drain(start: int) -> list[int]:
        out = []
        last = start
        for _ in range(3):
            events = await bus.wait_next(last, timeout=1.0)
            for e in events:
                out.append(e.seq)
                last = e.seq
            await asyncio.sleep(0)
        return out

    c1 = asyncio.create_task(drain(0))
    c2 = asyncio.create_task(drain(0))
    # 生产者补事件
    for i in range(3):
        bus.emit("tool_call", {"step_id": f"s{i}"})
        await asyncio.sleep(0)

    r1, r2 = await asyncio.gather(c1, c2)
    assert r1 == [1, 2, 3, 4]
    assert r2 == [1, 2, 3, 4]


def test_dropped_upto_records_eviction_boundary():
    bus = _bus(max_events=64)  # 容量下限 64
    for i in range(1, 71):  # 70 个事件 → 淘汰最老 6 个（seq 1..6）
        bus.emit("step", {"id": f"s{i}"})
    assert bus.dropped_upto() == 6
    assert bus.latest_seq() == 70
    # events_since(1) 已有洞（1..6 不在了）
    assert [e.seq for e in bus.events_since(1)] == list(range(7, 71))


@pytest.mark.asyncio
async def test_wait_next_raises_gap_when_last_seq_evicted():
    bus = _bus(max_events=64)
    for i in range(1, 71):
        bus.emit("step", {"id": f"s{i}"})

    with pytest.raises(BusGapError):
        await bus.wait_next(1, timeout=0.05)
    # last_seq 未淘汰 → 正常返回现存事件
    events = await bus.wait_next(6, timeout=0.05)
    assert [e.seq for e in events] == list(range(7, 71))
