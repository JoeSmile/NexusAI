"""LangGraph 管线包 — 避免在 import 时拉起完整图（防循环依赖）"""

__all__ = ["compiled_graph"]


def __getattr__(name: str):
    if name == "compiled_graph":
        from backend.pipeline.graph import compiled_graph

        return compiled_graph
    raise AttributeError(name)
