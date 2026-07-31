"""护栏结果基类"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GuardResult:
    """护栏检查结果"""

    action: str  # "pass" | "redacted" | "blocked" | "truncated"
    redacted_text: str
    reason: str
