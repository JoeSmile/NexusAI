"""Task 56 切片 4 — 事件总线 + 快照一致性。"""

from __future__ import annotations

from backend.core.plan.event_bus import PlanEventBus, get_run_bus, release_run_bus


def test_emit_order_and_snapshot() -> None:
    bus = PlanEventBus("tr_test")
    bus.publish_plan(
        goal="demo",
        steps=[
            {"id": "s1", "capability_id": "cap.a", "depends_on": []},
            {"id": "s2", "capability_id": "cap.b", "depends_on": ["s1"]},
        ],
    )
    bus.publish_step("s1", capability_id="cap.a", status="running")
    bus.publish_step("s1", capability_id="cap.a", status="succeeded", summary="ok")
    events = bus.events_all()
    assert [e.type for e in events] == ["plan", "step", "step"]
    assert events[0].seq == 1
    assert events[-1].seq == 3
    snap = bus.snapshot()
    assert snap.goal == "demo"
    assert len(snap.nodes) == 2
    assert snap.nodes[0].status in {"pending", "succeeded"}
    assert any(e.source == "s1" and e.target == "s2" for e in snap.edges)


def test_events_since_and_registry() -> None:
    release_run_bus("tr_reg")
    bus = get_run_bus("tr_reg")
    bus.emit("plan", {"goal": "x"})
    bus.emit("step", {"id": "s1", "status": "running"})
    assert bus.latest_seq() == 2
    assert len(bus.events_since(1)) == 1
    snap = get_run_bus("tr_reg").snapshot()
    assert snap.trace_id == "tr_reg"
    release_run_bus("tr_reg")


def test_event_bus_maxlen() -> None:
    bus = PlanEventBus("tr_max", max_events=128)
    for i in range(200):
        bus.emit("step", {"id": f"s{i}", "status": "running"})
    assert len(bus.events_all()) == 128
    assert bus.events_all()[0].seq == 73
