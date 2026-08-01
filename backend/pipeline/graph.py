"""LangGraph 图组装 — 编译完整管线"""

from __future__ import annotations

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


def build_pipeline():
    """构建并编译管线"""
    builder = StateGraph(PipelineState)

    builder.add_node("auth_check", auth_check)
    builder.add_node("load_memory", load_memory)
    builder.add_node("rate_limiter", rate_limiter)
    builder.add_node("cache_check", cache_check)
    builder.add_node("guardrails_input", guardrails_input)
    builder.add_node("analyze_parallel", analyze_parallel)
    builder.add_node("build_context", build_context)
    builder.add_node("experiment_hook", experiment_hook)
    builder.add_node("model_router", model_router)
    builder.add_node("llm_generate", llm_generate)
    builder.add_node("guardrails_output", guardrails_output)
    builder.add_node("write_memory", write_memory)
    builder.add_node("conversion_hook", conversion_hook)

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
