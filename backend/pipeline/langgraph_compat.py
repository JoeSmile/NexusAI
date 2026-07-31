"""
LangGraph 兼容层。

优先使用官方 `langgraph`；不可用时回退到本文件最小 StateGraph shim。
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Hashable
from typing import Any

END = "__end__"


class CompiledGraph:
    def __init__(
        self,
        nodes: dict[str, Callable],
        edges: dict[str, list[Hashable]],
        conditionals: dict[str, tuple[Callable, dict[str, Hashable]]],
        entry: str,
    ):
        self.nodes = nodes
        self.edges = edges
        self._conditionals = conditionals
        self._entry = entry

    async def ainvoke(self, state: dict) -> dict:
        current: Hashable = self._entry
        data = dict(state)
        visited = 0
        while current != END:
            visited += 1
            if visited > 100:
                raise RuntimeError("pipeline cycle guard triggered")
            fn = self.nodes[str(current)]
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
                nxt = self.edges.get(str(current), [END])
                current = nxt[0] if nxt else END
        return data


class StateGraph:
    def __init__(self, _state_schema: Any = None):
        self._nodes: dict[str, Callable] = {}
        self._edges: dict[str, list[Hashable]] = {}
        self._conditionals: dict[str, tuple[Callable, dict[str, Hashable]]] = {}
        self._entry: str | None = None

    def add_node(self, name: str, fn: Callable) -> None:
        self._nodes[name] = fn

    def set_entry_point(self, name: str) -> None:
        self._entry = name

    def add_edge(self, src: str, dst: Hashable) -> None:
        self._edges.setdefault(src, []).append(END if dst == END else dst)

    def add_conditional_edges(
        self,
        src: str,
        router: Callable,
        mapping: dict[str, Hashable],
    ) -> None:
        norm: dict[str, Hashable] = {k: (END if v == END else v) for k, v in mapping.items()}
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


_USING_OFFICIAL = False
try:
    from langgraph.graph import END as _LG_END  # type: ignore
    from langgraph.graph import StateGraph as _LG_StateGraph  # type: ignore

    StateGraph = _LG_StateGraph  # type: ignore
    END = _LG_END  # type: ignore
    _USING_OFFICIAL = True
except Exception:
    pass


def using_official_langgraph() -> bool:
    return _USING_OFFICIAL
