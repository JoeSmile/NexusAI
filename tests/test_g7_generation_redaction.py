"""G7 — generation-exit student PII redaction."""

from __future__ import annotations

import json

import pytest

from backend.pipeline.nodes.guardrails_output import apply_student_output_redaction
from backend.pipeline.state import make_initial_state


def test_apply_student_output_redaction_strips_name():
    state = make_initial_state("t1", "u1", "s1", "写口播")
    state["response"] = "请联系李明家长确认课时"
    state["warm_memory"] = {
        "entity:李明": json.dumps(
            {"name": "李明", "relation": "学生", "text": "李明"}
        )
    }
    apply_student_output_redaction(state)
    assert "李明" not in (state.get("response") or "")
    assert state.get("student_pii_redacted") is True


@pytest.mark.asyncio
async def test_guardrails_output_runs_redaction():
    from backend.pipeline.nodes.guardrails_output import guardrails_output

    state = make_initial_state("t1", "u1", "s1", "hi")
    state["response"] = "学员张伟表现很好"
    state["warm_memory"] = {
        "entity:张伟": json.dumps(
            {"name": "张伟", "relation": "学员", "text": "张伟"}
        )
    }
    out = await guardrails_output(state)
    assert "张伟" not in (out.get("response") or "")
