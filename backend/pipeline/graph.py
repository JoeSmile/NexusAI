"""LangGraph 图组装 — 编译完整管线"""

from __future__ import annotations

import inspect
from typing import Any

from backend.pipeline.langgraph_compat import END, StateGraph
from backend.pipeline.nodes.analyze_parallel import analyze_parallel
from backend.pipeline.nodes.auth_check import auth_check
from backend.pipeline.nodes.build_context import build_context
from backend.pipeline.nodes.cache_check import cache_check, should_skip_to_end
from backend.pipeline.nodes.conversion_hook import conversion_hook
from backend.pipeline.nodes.experiment_hook import experiment_hook
from backend.pipeline.nodes.guardrails_input import (
    guardrails_input,
    should_block_to_end,
)
from backend.pipeline.nodes.guardrails_output import guardrails_output
from backend.pipeline.nodes.llm_generate import llm_generate
from backend.pipeline.nodes.load_memory import load_memory
from backend.pipeline.nodes.model_router import model_router, route_short_or_long
from backend.pipeline.nodes.rate_limiter import rate_limiter
from backend.pipeline.nodes.write_memory import write_memory
from backend.pipeline.state import PipelineState


def _lf_node(name: str, fn: Any) -> Any:
    """LangGraph 节点包装 — 修复 Langfuse span 树(GAP-08)。

    LangGraph 执行节点时 langfuse SDK 的 contextvar 观察栈丢失,节点观察对象
    变成平铺(parent=None)/独立根 trace。此处把入口读取的根 trace/span id
    经 state 显式传给节点;栈为空时 SDK 采纳显式 parent,span 正确嵌套且
    带真实耗时(start/end)。
    """

    _KEYS = ("_lf_trace_id", "_lf_parent_obs_id")

    async def wrapped(state: dict, *args: Any, **kwargs: Any) -> Any:
        tid = state.get("_lf_trace_id") if isinstance(state, dict) else None
        oid = state.get("_lf_parent_obs_id") if isinstance(state, dict) else None
        clean = (
            {k: v for k, v in state.items() if k not in _KEYS}
            if isinstance(state, dict)
            else state
        )
        if tid and oid:
            from backend.observability.sampling import tracing_enabled

            if tracing_enabled():
                kwargs["langfuse_parent_trace_id"] = tid
                kwargs["langfuse_parent_observation_id"] = oid
        r = fn(clean, *args, **kwargs)
        result = await r if inspect.isawaitable(r) else r
        if isinstance(result, dict) and tid and oid:
            result["_lf_trace_id"] = tid
            result["_lf_parent_obs_id"] = oid
        return result

    return wrapped


def build_pipeline():
    """构建并编译管线"""
    builder = StateGraph(PipelineState)

    builder.add_node("auth_check", _lf_node("auth_check", auth_check))
    builder.add_node("load_memory", _lf_node("load_memory", load_memory))
    builder.add_node("rate_limiter", _lf_node("rate_limiter", rate_limiter))
    builder.add_node("cache_check", _lf_node("cache_check", cache_check))
    builder.add_node("guardrails_input", _lf_node("guardrails_input", guardrails_input))
    builder.add_node("analyze_parallel", _lf_node("analyze_parallel", analyze_parallel))
    builder.add_node("build_context", _lf_node("build_context", build_context))
    builder.add_node("experiment_hook", _lf_node("experiment_hook", experiment_hook))
    builder.add_node("model_router", _lf_node("model_router", model_router))
    builder.add_node("llm_generate", _lf_node("llm_generate", llm_generate))
    builder.add_node("guardrails_output", _lf_node("guardrails_output", guardrails_output))
    builder.add_node("write_memory", _lf_node("write_memory", write_memory))
    builder.add_node("conversion_hook", _lf_node("conversion_hook", conversion_hook))

    builder.set_entry_point("auth_check")

    builder.add_edge("auth_check", "load_memory")
    builder.add_edge("load_memory", "rate_limiter")
    builder.add_edge("rate_limiter", "cache_check")

    builder.add_conditional_edges(
        "cache_check",
        should_skip_to_end,
        {
            "end": END,
            "continue": "guardrails_input",
        },
    )

    builder.add_conditional_edges(
        "guardrails_input",
        should_block_to_end,
        {
            "end": END,
            "continue": "analyze_parallel",
        },
    )
    builder.add_edge("analyze_parallel", "build_context")
    builder.add_edge("build_context", "experiment_hook")
    builder.add_edge("experiment_hook", "model_router")

    builder.add_conditional_edges(
        "model_router",
        route_short_or_long,
        {
            "conversion_hook": "conversion_hook",
            "llm_generate": "llm_generate",
        },
    )

    builder.add_edge("llm_generate", "guardrails_output")
    builder.add_edge("guardrails_output", "write_memory")
    builder.add_edge("write_memory", "conversion_hook")
    builder.add_edge("conversion_hook", END)

    return builder.compile()


compiled_graph = build_pipeline()
