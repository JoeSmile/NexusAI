"""Publish gates for skill_assets (Task 43.4)."""

from __future__ import annotations

import json
import re
from typing import Any

from packages.guardrails.pii_patterns import PII_PATTERNS
from packages.workflow.ir import _FORBIDDEN_PARAM_KEYS

# 密钥 / 凭据启发式
_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*\S+"),
    re.compile(r"(?i)sk-[a-zA-Z0-9]{10,}"),
    re.compile(r"(?i)bearer\s+[a-z0-9\-_\.]{10,}"),
]

# 租户标识启发式（禁止把 tenant_id 写进可共享配方）
_TENANT_MARKERS = re.compile(
    r"(?i)\b(tenant_id|tenant-id)\s*[:=]\s*['\"]?[a-z0-9_\-]{2,}"
)


class GateReject(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _scan_text(text: str) -> None:
    if not text:
        return
    for name, pattern in PII_PATTERNS.items():
        if re.search(pattern, text):
            raise GateReject("GATE_PII", f"pii_detected:{name}")
    for pat in _SECRET_PATTERNS:
        if pat.search(text):
            raise GateReject("GATE_SECRET", "secret_pattern_detected")
    if _TENANT_MARKERS.search(text):
        raise GateReject("GATE_TENANT", "tenant_marker_detected")


def _scan_ir_skeleton(skeleton: dict[str, Any] | None) -> None:
    raw = json.dumps(skeleton or {}, ensure_ascii=False)
    _scan_text(raw)
    body = skeleton if isinstance(skeleton, dict) else {}
    chunks: list[Any] = []
    steps = body.get("steps")
    if isinstance(steps, list):
        chunks.extend(steps)
    nodes = body.get("nodes")
    if isinstance(nodes, list):
        chunks.extend(nodes)
    for step in chunks:
        if not isinstance(step, dict):
            continue
        params = step.get("params") or {}
        if not isinstance(params, dict):
            continue
        bad = set(params) & _FORBIDDEN_PARAM_KEYS
        if bad:
            raise GateReject(
                "GATE_SUPPLY",
                f"forbidden_param_keys:{sorted(bad)}",
            )


def run_publish_gates(
    *,
    cot_template: str,
    ir_skeleton: dict[str, Any] | None,
    required_permissions: list[str] | None = None,
) -> list[str]:
    """
    三关：脱敏 / 供应链 / 权限不放大。
    返回继承给使用者的 required_permissions（配方不携带放大权限）。
    """
    _scan_text(cot_template or "")
    _scan_ir_skeleton(ir_skeleton if isinstance(ir_skeleton, dict) else {})
    # 权限不放大：发布物只保留声明的 required_permissions 副本，不含执行凭据
    perms = [p for p in (required_permissions or []) if isinstance(p, str) and p.strip()]
    return perms
