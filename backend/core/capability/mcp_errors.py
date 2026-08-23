"""Unified MCP error model (Task 66 slice 3)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class McpErrorCode(StrEnum):
    MCP_PROTOCOL_ERROR = "MCP_PROTOCOL_ERROR"
    MCP_SERVER_CRASH = "MCP_SERVER_CRASH"
    MCP_TIMEOUT = "MCP_TIMEOUT"
    MCP_SPEC_INVALID = "MCP_SPEC_INVALID"
    GOVERNANCE_DENIED = "GOVERNANCE_DENIED"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    MCP_NOT_CONFIGURED = "MCP_NOT_CONFIGURED"


_RETRYABLE = frozenset(
    {
        McpErrorCode.MCP_PROTOCOL_ERROR,
        McpErrorCode.MCP_SERVER_CRASH,
        McpErrorCode.MCP_TIMEOUT,
    }
)


@dataclass
class McpError(Exception):
    code: str
    message: str
    inner_error: Any = None
    retryable: bool = False
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        if not self.retryable:
            self.retryable = self.code in {c.value for c in _RETRYABLE}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "inner_error": self.inner_error,
            "retryable": self.retryable,
            "trace_id": self.trace_id,
        }


def map_jsonrpc_error(code: int | None, message: str, *, trace_id: str = "") -> McpError:
    """Map JSON-RPC error codes to internal MCP errors."""
    code_i = int(code) if code is not None else -32603
    if code_i == -32600:
        err = McpErrorCode.MCP_PROTOCOL_ERROR
    elif code_i in (-32601, -32602):
        err = McpErrorCode.MCP_PROTOCOL_ERROR
    else:
        err = McpErrorCode.MCP_PROTOCOL_ERROR
    return McpError(
        code=err.value,
        message=message or "jsonrpc_error",
        inner_error={"jsonrpc_code": code_i},
        trace_id=trace_id or uuid.uuid4().hex,
        retryable=code_i == -32603,
    )
