"""
Minimal StateGraph shim — Batch 4 可运行管线。

真实 `langgraph` 当前与项目 pydantic<2 锁冲突；API 对齐 batch-04 用法：
add_node / add_edge / add_conditional_edges / set_entry_point / compile / ainvoke。
Batch 6 升级 pydantic v2 后可切换为官方 langgraph。
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Hashable

END = "__end__"


class CompiledGraph:
    def __init__(
        self,
        nodes: dict[str, Callable],
        edges: dict[str, list[str]],
        conditionals: dict[str, tuple[Callable, dict[str, str]]],
        entry: str,
    ):
        self.nodes = nodes
        self.edges = edges
        self._conditionals = conditionals
        self._entry = entry

    async def ainvoke(self, state: dict) -> dict:
        current = self._entry
        data = dict(state)
        visited = 0
        while current != END:
            visited += 1
            if visited > 100:
                raise RuntimeError("pipeline cycle guard triggered")
            fn = self.nodes[current]
            result = fn(data)
            if inspect.isawaitable(result):
                data = await result
            else:
                data = result
            if current in self._conditionals:
                router, mapping = self._conditionals[current]
                key = router(data)
                current = mapping[key]
            else:
                nxt = self.edges.get(current, [END])
                current = nxt[0] if nxt else END
        return data


class StateGraph:
    def __init__(self, _state_schema: Any = None):
        self._nodes: dict[str, Callable] = {}
        self._edges: dict[str, list[str]] = {}
        self._conditionals: dict[str, tuple[Callable, dict[str, str]]] = {}
        self._entry: str | None = None

    def add_node(self, name: str, fn: Callable) -> None:
        self._nodes[name] = fn

    def set_entry_point(self, name: str) -> None:
        self._entry = name

    def add_edge(self, src: str, dst: Hashable) -> None:
        self._edges.setdefault(src, []).append(dst if dst != END else END)

    def add_conditional_edges(
        self,
        src: str,
        router: Callable,
        mapping: dict[str, Hashable],
    ) -> None:
        norm = {k: (END if v == END else v) for k, v in mapping.items()}
        self._conditionals[src] = (router, norm)

    def compile(self) -> CompiledGraph:
        if not self._entry:
            raise ValueError("entry point not set")
        return CompiledGraph(
            nodes=dict(self._nodes),
            edges={k: list(v) for k, v in self._edges.items()},
            conditionals=dict(self._conditionals),
            entry=self._entry,
        )


try:
    from langgraph.graph import END as _LG_END  # type: ignore
    from langgraph.graph import StateGraph as _LG_StateGraph  # type: ignore

    StateGraph = _LG_StateGraph  # type: ignore
    END = _LG_END  # type: ignore
except Exception:
    # ImportError 或 pydantic 不兼容时继续用本文件 shim
    pass
