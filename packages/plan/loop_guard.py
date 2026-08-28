"""Loop-Guard — duplicate tool invoke detection + per-session cap (Task 62 slice 1)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from packages.audit import write_audit_sync


class LoopGuardError(Exception):
    """Raised when loop-guard blocks an invoke."""

    def __init__(self, reason: str, *, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail or reason


_DEFAULT_DUP_STREAK = 3
_DEFAULT_SESSION_CAP = 50


def loop_guard_enabled() -> bool:
    return (os.getenv("LOOP_GUARD_ENABLED", "1")).strip().lower() not in (
        "0",
        "false",
        "no",
    )


def _max_dup_streak() -> int:
    raw = (os.getenv("LOOP_GUARD_MAX_DUP_STREAK") or "").strip()
    try:
        return max(2, int(raw)) if raw else _DEFAULT_DUP_STREAK
    except ValueError:
        return _DEFAULT_DUP_STREAK


def _session_cap() -> int:
    raw = (os.getenv("LOOP_GUARD_SESSION_CAP") or "").strip()
    try:
        return max(1, int(raw)) if raw else _DEFAULT_SESSION_CAP
    except ValueError:
        return _DEFAULT_SESSION_CAP


def invoke_fingerprint(cap_id: str, payload: dict[str, Any] | None) -> str:
    """Canonical key for duplicate detection."""
    params = payload if isinstance(payload, dict) else {}
    blob = json.dumps(
        {"capability_id": cap_id, "params": params},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return blob


@dataclass
class LoopGuardState:
    streak_key: str | None = None
    streak_count: int = 0
    invoke_total: int = 0


class LoopGuard:
    """Tracks per-session invoke fingerprints; blocks dup streaks and caps."""

    def __init__(self, state: LoopGuardState | None = None) -> None:
        st = state or LoopGuardState()
        self._streak_key = st.streak_key
        self._streak_count = int(st.streak_count)
        self._invoke_total = int(st.invoke_total)

    @classmethod
    def from_pipeline(cls, pipeline: dict[str, Any] | None) -> LoopGuard:
        if not pipeline:
            return cls()
        return cls(
            LoopGuardState(
                streak_key=pipeline.get("loop_guard_streak_key"),
                streak_count=int(pipeline.get("loop_guard_streak_count") or 0),
                invoke_total=int(pipeline.get("loop_guard_invoke_total") or 0),
            )
        )

    def persist(self, pipeline: dict[str, Any]) -> None:
        pipeline["loop_guard_streak_key"] = self._streak_key
        pipeline["loop_guard_streak_count"] = self._streak_count
        pipeline["loop_guard_invoke_total"] = self._invoke_total

    def check(
        self,
        cap_id: str,
        payload: dict[str, Any] | None,
        *,
        tenant_id: str = "",
        user_id: str = "",
        trace_id: str = "",
    ) -> None:
        if not loop_guard_enabled():
            return

        cap = (cap_id or "").strip()
        if not cap:
            return

        if self._invoke_total >= _session_cap():
            self._audit_block(
                reason="session_cap",
                cap_id=cap,
                streak=self._streak_count,
                tenant_id=tenant_id,
                user_id=user_id,
                trace_id=trace_id,
            )
            raise LoopGuardError(
                "session_cap",
                detail="检测到重复执行，已停止（会话工具调用上限）",
            )

        fp = invoke_fingerprint(cap, payload or {})
        if fp == self._streak_key:
            self._streak_count += 1
        else:
            self._streak_key = fp
            self._streak_count = 1

        self._invoke_total += 1

        if self._streak_count >= _max_dup_streak():
            self._audit_block(
                reason="duplicate_streak",
                cap_id=cap,
                streak=self._streak_count,
                tenant_id=tenant_id,
                user_id=user_id,
                trace_id=trace_id,
            )
            raise LoopGuardError(
                "duplicate_streak",
                detail="检测到重复执行，已停止",
            )

    def _audit_block(
        self,
        *,
        reason: str,
        cap_id: str,
        streak: int,
        tenant_id: str,
        user_id: str,
        trace_id: str,
    ) -> None:
        detail = json.dumps(
            {
                "reason": reason,
                "streak": streak,
                "invoke_total": self._invoke_total,
                "capability_id": cap_id,
            },
            ensure_ascii=False,
        )
        write_audit_sync(
            {
                "tenant_id": tenant_id or "default",
                "user_id": user_id or "system",
                "action": "orchestrator.loop_guard",
                "trace_id": trace_id or "",
                "input_text": cap_id[:200],
                "output_text": detail[:2000],
                "model": cap_id,
                "created_at": datetime.utcnow(),
            }
        )
