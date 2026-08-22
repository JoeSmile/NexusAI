"""Structured sub-task conclusion blackboard (Task 61 slice 3)."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from backend.core.audit import write_audit_sync

_MAX_FACT_CHARS = 500
_DEFAULT_CAPACITY = 32
_DEFAULT_TTL_S = 3600
_MIN_CONFIDENCE = 0.2


@dataclass
class BlackboardEntry:
    source_agent_id: str
    document_ids_ref: list[str]
    fact_content: str
    confidence: float
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Blackboard:
    """In-process blackboard with capacity / TTL / confidence eviction."""

    def __init__(
        self,
        *,
        capacity: int | None = None,
        ttl_s: float | None = None,
    ) -> None:
        self._capacity = capacity or int(
            os.getenv("BLACKBOARD_MAX_ENTRIES") or _DEFAULT_CAPACITY
        )
        self._ttl_s = float(os.getenv("BLACKBOARD_TTL_S") or ttl_s or _DEFAULT_TTL_S)
        self._entries: list[BlackboardEntry] = []

    def add(
        self,
        entry: BlackboardEntry,
        *,
        tenant_id: str = "default",
        user_id: str = "system",
        trace_id: str = "",
    ) -> bool:
        fact = (entry.fact_content or "").strip()
        if not fact:
            return False
        if len(fact) > _MAX_FACT_CHARS:
            raise ValueError("blackboard_fact_too_long")
        if entry.confidence < _MIN_CONFIDENCE:
            return False
        self._evict_expired()
        self._entries.append(
            BlackboardEntry(
                source_agent_id=entry.source_agent_id,
                document_ids_ref=list(entry.document_ids_ref or []),
                fact_content=fact[:_MAX_FACT_CHARS],
                confidence=float(entry.confidence),
                created_at=entry.created_at or time.time(),
            )
        )
        self._enforce_capacity()
        self._audit_add(entry, tenant_id=tenant_id, user_id=user_id, trace_id=trace_id)
        return True

    def list_entries(self) -> list[dict[str, Any]]:
        self._evict_expired()
        return [e.to_dict() for e in self._entries]

    def synthesize(self, goal: str = "") -> str:
        self._evict_expired()
        lines: list[str] = []
        if goal:
            lines.append(f"目标：{goal}")
        for e in self._entries:
            refs = ",".join(e.document_ids_ref[:5])
            ref_part = f" refs={refs}" if refs else ""
            lines.append(
                f"- [{e.source_agent_id}] {e.fact_content} (conf={e.confidence:.2f}{ref_part})"
            )
        return "\n".join(lines)

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> Blackboard:
        bb = cls()
        for raw in state.get("blackboard") or []:
            if not isinstance(raw, dict):
                continue
            try:
                bb._entries.append(
                    BlackboardEntry(
                        source_agent_id=str(raw.get("source_agent_id") or "agent"),
                        document_ids_ref=[
                            str(x) for x in (raw.get("document_ids_ref") or [])
                        ],
                        fact_content=str(raw.get("fact_content") or ""),
                        confidence=float(raw.get("confidence") or 0.5),
                        created_at=float(raw.get("created_at") or time.time()),
                    )
                )
            except (TypeError, ValueError):
                continue
        return bb

    def _evict_expired(self) -> None:
        now = time.time()
        self._entries = [e for e in self._entries if now - e.created_at <= self._ttl_s]

    def _enforce_capacity(self) -> None:
        if len(self._entries) <= self._capacity:
            return
        self._entries.sort(key=lambda e: (e.confidence, e.created_at))
        self._entries = self._entries[-self._capacity :]

    def _audit_add(
        self,
        entry: BlackboardEntry,
        *,
        tenant_id: str,
        user_id: str,
        trace_id: str,
    ) -> None:
        try:
            write_audit_sync(
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "action": "blackboard.add",
                    "trace_id": trace_id,
                    "input_text": entry.source_agent_id[:200],
                    "output_text": json.dumps(
                        {
                            "document_ids_ref": entry.document_ids_ref,
                            "fact_content": entry.fact_content[:300],
                            "confidence": entry.confidence,
                        },
                        ensure_ascii=False,
                    )[:4000],
                    "model": "blackboard",
                }
            )
        except Exception:
            pass


def entry_from_step_result(
    *,
    step_id: str,
    capability_id: str,
    outcome: dict[str, Any],
    document_ids_ref: list[str] | None = None,
) -> BlackboardEntry | None:
    text = str(outcome.get("output") or outcome.get("text") or "").strip()
    if not text or outcome.get("skipped"):
        return None
    if len(text) > _MAX_FACT_CHARS:
        return None
    conf = 0.9 if outcome.get("ok", True) else 0.4
    return BlackboardEntry(
        source_agent_id=f"{step_id}:{capability_id}",
        document_ids_ref=list(document_ids_ref or []),
        fact_content=text,
        confidence=conf,
    )
