"""
Protocol 2: Tool Executor — 工具执行抽象

Defines the contract for tool execution. Tools always return ToolResult
and never raise exceptions (error in .error field).

Adapted for ContextGate:
- 工具包含LLM Gateway专用工具 (日历、提醒服务等)
- ToolResult 包含工具类别标记
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolResult:
    """工具执行结果 — 永不抛异常，错误在 error 字段返回"""

    output: str = ""
    error: str | None = None
    metadata: dict = field(default_factory=dict)
    # LLM Gateway扩展字段
    tool_category: str = "general"  # "memory" | "calendar" | "general"

    @property
    def is_error(self) -> bool:
        return self.error is not None

    @property
    def is_success(self) -> bool:
        return self.error is None


class ToolExecutor(Protocol):
    """Protocol for tool execution — never throws, error in ToolResult."""

    async def execute(self, name: str, args: dict) -> ToolResult: ...

    def list_tools(self) -> list[dict]:
        """返回所有可用工具的描述列表"""
        ...
