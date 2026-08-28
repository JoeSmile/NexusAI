"""管线路由与 A/B conversion 钩子测试(Task 22 收尾 review 回归)"""

import pytest

from packages.pipeline.nodes.conversion_hook import conversion_hook
from packages.pipeline.nodes.model_router import route_short_or_long
from packages.pipeline.nodes.orchestrator import route_after_orchestrator

# ── route_short_or_long: 反向判断(仅非流式长路径去 llm_generate)──


def test_route_long_path_to_llm():
    state = {"finish_reason": "routed_to_llm"}
    assert route_short_or_long(state) == "llm_generate"


def test_route_skill_success_to_write_memory():
    state = {"finish_reason": "skill_executed"}
    assert route_short_or_long(state) == "write_memory"


def test_route_skill_error_to_write_memory():
    """skill 失败(error)必须终止并落库,不得遗漏式落进 llm_generate"""
    state = {"finish_reason": "error"}
    assert route_short_or_long(state) == "write_memory"


def test_route_arbitrary_skill_error_string_to_write_memory():
    """skill 返回的非枚举错误字符串(如 TIMEOUT)同样必须终止并落库"""
    state = {"finish_reason": "TIMEOUT"}
    assert route_short_or_long(state) == "write_memory"


def test_route_approval_to_write_memory():
    state = {"finish_reason": "PENDING_APPROVAL"}
    assert route_short_or_long(state) == "write_memory"


def test_route_stream_short_path_to_write_memory():
    """流式入口但短路径已有响应: 仍走 write_memory（SSE 不会再生成）"""
    state = {"finish_reason": "skill_executed", "stream_mode": True}
    assert route_short_or_long(state) == "write_memory"


def test_route_stream_mode_never_llm_generate():
    """流式长路径: 不进 llm_generate，也不在图内 write_memory（SSE 结束后补跑）"""
    state = {"finish_reason": "routed_to_llm", "stream_mode": True}
    assert route_short_or_long(state) == "conversion_hook"


def test_route_orchestrated_to_write_memory():
    assert route_after_orchestrator({"finish_reason": "orchestrated"}) == "write_memory"


def test_route_orchestrator_cancelled_to_write_memory():
    assert route_after_orchestrator({"finish_reason": "cancelled"}) == "write_memory"


def test_route_orchestrator_fallback_still_model_router():
    assert route_after_orchestrator({"finish_reason": "routed_to_llm"}) == "model_router"


# ── conversion_hook: 有实验且有响应才记转化 ──


@pytest.mark.asyncio
async def test_conversion_no_experiment_skips(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        "packages.pipeline.nodes.conversion_hook.record_event",
        lambda **kw: calls.append(kw),
    )
    state = {"user_id": "u1", "response": "hi", "session_id": "s1"}
    out = await conversion_hook(state)
    assert out is state
    assert calls == []


@pytest.mark.asyncio
async def test_conversion_experiment_no_response_skips(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        "packages.pipeline.nodes.conversion_hook.record_event",
        lambda **kw: calls.append(kw),
    )
    state = {"user_id": "u1", "ab_experiment_id": "exp1", "ab_variant": "A"}
    await conversion_hook(state)
    assert calls == []


@pytest.mark.asyncio
async def test_conversion_recorded(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        "packages.pipeline.nodes.conversion_hook.record_event",
        lambda **kw: calls.append(kw),
    )
    state = {
        "user_id": "u1",
        "ab_experiment_id": "exp1",
        "ab_variant": "A",
        "response": "答案",
        "trace_id": "t1",
        "session_id": "s1",
    }
    await conversion_hook(state)
    assert len(calls) == 1
    ev = calls[0]
    assert ev["event_type"] == "conversion"
    assert ev["experiment_id"] == "exp1"
    assert ev["group"] == "A"
    assert ev["event_data"] == {"trace_id": "t1", "session_id": "s1"}


@pytest.mark.asyncio
async def test_conversion_db_failure_silent(monkeypatch):
    def boom(**kw):
        raise RuntimeError("db down")

    monkeypatch.setattr("packages.pipeline.nodes.conversion_hook.record_event", boom)
    state = {
        "user_id": "u1",
        "ab_experiment_id": "exp1",
        "ab_variant": "B",
        "response": "答案",
    }
    out = await conversion_hook(state)
    assert out is state  # DB 故障不拖垮管线
