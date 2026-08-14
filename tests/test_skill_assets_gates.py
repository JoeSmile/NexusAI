"""Task 43.4 — publish gates."""

from __future__ import annotations

import pytest

from backend.core.skill_assets.gates import GateReject, run_publish_gates


def test_gate_rejects_pii_phone():
    with pytest.raises(GateReject) as ei:
        run_publish_gates(
            cot_template="call user 13800138000 now",
            ir_skeleton={},
        )
    assert ei.value.code == "GATE_PII"


def test_gate_rejects_forbidden_params():
    with pytest.raises(GateReject) as ei:
        run_publish_gates(
            cot_template="ok",
            ir_skeleton={
                "steps": [{"capability_id": "c", "params": {"api_key": "x"}}]
            },
        )
    assert ei.value.code == "GATE_SUPPLY"


def test_gate_permissions_not_amplified():
    perms = run_publish_gates(
        cot_template="safe template",
        ir_skeleton={"steps": [{"capability_id": "c", "params": {}}]},
        required_permissions=["chat:write", "kb:read"],
    )
    assert perms == ["chat:write", "kb:read"]
