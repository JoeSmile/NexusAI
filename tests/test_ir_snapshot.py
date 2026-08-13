"""Wave D2 — IR snapshot freeze + idempotency key."""

from backend.core.workflow.runner import freeze_ir_snapshot, idempotency_key


def test_freeze_ir_snapshot_deepcopy():
    ir = {"nodes": [{"node_id": "n1", "params": {"q": "a"}}]}
    snap = freeze_ir_snapshot(ir)
    ir["nodes"][0]["params"]["q"] = "b"
    assert snap["nodes"][0]["params"]["q"] == "a"


def test_idempotency_key():
    assert idempotency_key("r1", "n1") == "r1:n1"
