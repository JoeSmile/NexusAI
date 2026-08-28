"""Wave D4 — runner audit uses run_id / node_id without plaintext params."""

from __future__ import annotations

from unittest.mock import patch

from packages.workflow.runner import _audit


def test_audit_includes_run_and_node_ids():
    captured = {}

    def _capture(record):
        captured.update(record)

    with patch("packages.workflow.runner_shared.write_audit_sync", _capture):
        _audit(
            tenant_id="t1",
            user_id="u1",
            action="workflow.node.succeeded",
            credential_kind="human_session",
            run_id="run-1",
            node_id="n1",
            output_text="evidence_count=1",
        )
    assert captured["run_id"] == "run-1"
    assert captured["node_id"] == "n1"
    assert "api_key" not in (captured.get("input_text") or "")
    assert captured["input_text"] == ""
