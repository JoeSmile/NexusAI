"""Execution policy for builtin/MCP tools (Task 66 slice 1)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

IsolationMode = Literal["direct", "sandbox", "subprocess"]


@dataclass(frozen=True)
class ExecPolicy:
    timeout_s: float = 30.0
    hard_kill_timeout_s: float = 60.0
    max_retries: int = 1
    rate_limit_per_min: int = 120
    isolation_mode: IsolationMode = "direct"
    max_payload_bytes: int = 256_000
    max_concurrent_mcp_subprocess: int = 4

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeout_s": self.timeout_s,
            "hard_kill_timeout_s": self.hard_kill_timeout_s,
            "max_retries": self.max_retries,
            "rate_limit_per_min": self.rate_limit_per_min,
            "isolation_mode": self.isolation_mode,
            "max_payload_bytes": self.max_payload_bytes,
            "max_concurrent_mcp_subprocess": self.max_concurrent_mcp_subprocess,
        }


def global_default_exec_policy() -> ExecPolicy:
    return ExecPolicy(
        timeout_s=float(os.getenv("CAP_EXEC_TIMEOUT_S", "30")),
        hard_kill_timeout_s=float(os.getenv("CAP_EXEC_HARD_KILL_S", "60")),
        max_retries=int(os.getenv("CAP_EXEC_MAX_RETRIES", "1")),
        rate_limit_per_min=int(os.getenv("CAP_EXEC_RATE_LIMIT", "120")),
        isolation_mode="direct",  # type: ignore[assignment]
        max_payload_bytes=int(os.getenv("CAP_EXEC_MAX_PAYLOAD", "256000")),
        max_concurrent_mcp_subprocess=int(
            os.getenv("CAPABILITY_MCP_MAX_GLOBAL_CONCURRENCY", "4")
        ),
    )


def resolve_exec_policy(spec: dict[str, Any] | None) -> ExecPolicy:
    """Tool-level overrides on top of global defaults."""
    base = global_default_exec_policy()
    if not spec:
        return base
    raw = spec.get("exec_policy")
    if not isinstance(raw, dict):
        return base
    return ExecPolicy(
        timeout_s=float(raw.get("timeout_s", base.timeout_s)),
        hard_kill_timeout_s=float(
            raw.get("hard_kill_timeout_s", base.hard_kill_timeout_s)
        ),
        max_retries=int(raw.get("max_retries", base.max_retries)),
        rate_limit_per_min=int(raw.get("rate_limit_per_min", base.rate_limit_per_min)),
        isolation_mode=str(raw.get("isolation_mode", base.isolation_mode)),  # type: ignore[arg-type]
        max_payload_bytes=int(raw.get("max_payload_bytes", base.max_payload_bytes)),
        max_concurrent_mcp_subprocess=int(
            raw.get("max_concurrent_mcp_subprocess", base.max_concurrent_mcp_subprocess)
        ),
    )
