"""Structured sub-task conclusion blackboard (Task 61 slice 3 + spec 2026-08-22)."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from backend.core.audit import write_audit_sync
from backend.core.guardrails.rag_sanitize import sanitize_fragment

_MAX_FACT_CHARS = 800
_DEFAULT_CAPACITY = 50
_DEFAULT_TTL_S = 3600
_MIN_CONFIDENCE = 0.2
_HOT_LIMIT = 12
_TOKEN_BUDGET_CHARS = 4000


@dataclass
class BlackboardEntry:
    source_agent_id: str
    document_ids_ref: list[str]
    fact_content: str
    confidence: float
    topic: str = "fact.general"
    entry_id: str = ""
    trace_id: str = ""
    status: str = "active"
    version: int = 1
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Blackboard:
    """Session blackboard: topic-keyed entries, capacity/TTL/conflict flag."""

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
        self._by_topic: dict[str, BlackboardEntry] = {}

    def add(
        self,
        entry: BlackboardEntry,
        *,
        tenant_id: str = "default",
        user_id: str = "system",
        trace_id: str = "",
    ) -> bool:
        topic = (entry.topic or "fact.general").strip()
        return self.add_topic(
            topic=topic,
            fact_content=entry.fact_content,
            source_agent_id=entry.source_agent_id,
            document_ids_ref=entry.document_ids_ref,
            confidence=entry.confidence,
            tenant_id=tenant_id,
            user_id=user_id,
            trace_id=trace_id or entry.trace_id,
        )

    def add_topic(
        self,
        *,
        topic: str,
        fact_content: str,
        source_agent_id: str,
        document_ids_ref: list[str] | None = None,
        confidence: float,
        tenant_id: str = "default",
        user_id: str = "system",
        trace_id: str = "",
    ) -> bool:
        fact_raw = (fact_content or "").strip()
        if not fact_raw:
            return False
        if len(fact_raw) > _MAX_FACT_CHARS:
            raise ValueError("blackboard_fact_too_long")
        fact, _flags = sanitize_fragment(fact_raw, max_chars=_MAX_FACT_CHARS)
        if confidence < _MIN_CONFIDENCE:
            return False
        self._evict_expired()
        topic = topic.strip()
        prev = self._by_topic.get(topic)
        version = (prev.version + 1) if prev else 1
        status = "active"
        if prev and prev.fact_content.strip() != fact.strip():
            prev.status = "conflict"
            status = "conflict"
        entry = BlackboardEntry(
            entry_id=str(uuid.uuid4()),
            topic=topic,
            source_agent_id=source_agent_id,
            document_ids_ref=list(document_ids_ref or []),
            fact_content=fact[:_MAX_FACT_CHARS],
            confidence=float(confidence),
            trace_id=trace_id,
            status=status,
            version=version,
            created_at=time.time(),
        )
        self._by_topic[topic] = entry
        self._enforce_capacity()
        self._audit_add(entry, tenant_id=tenant_id, user_id=user_id, trace_id=trace_id)
        return True

    def list_entries(self) -> list[dict[str, Any]]:
        self._evict_expired()
        return [e.to_dict() for e in sorted(self._by_topic.values(), key=lambda x: x.created_at)]

    def hot_entries(self, *, limit: int = _HOT_LIMIT) -> list[BlackboardEntry]:
        self._evict_expired()
        active = [
            e
            for e in self._by_topic.values()
            if e.status in {"active", "conflict"}
        ]
        active.sort(key=lambda e: (e.confidence, e.created_at), reverse=True)
        return active[:limit]

    def synthesize(self, goal: str = "") -> str:
        lines: list[str] = []
        if goal:
            lines.append(f"目标：{goal}")
        used = 0
        for e in self.hot_entries():
            refs = ",".join(e.document_ids_ref[:5])
            ref_part = f" refs={refs}" if refs else ""
            line = (
                f"- [{e.topic}] [{e.source_agent_id}] {e.fact_content} "
                f"(conf={e.confidence:.2f}{ref_part})"
            )
            if used + len(line) > _TOKEN_BUDGET_CHARS:
                break
            lines.append(line)
            used += len(line)
        return "\n".join(lines)

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> Blackboard:
        bb = cls()
        for raw in state.get("blackboard") or []:
            if not isinstance(raw, dict):
                continue
            try:
                entry = BlackboardEntry(
                    entry_id=str(raw.get("entry_id") or uuid.uuid4()),
                    topic=str(raw.get("topic") or "fact.general"),
                    source_agent_id=str(raw.get("source_agent_id") or "agent"),
                    document_ids_ref=[
                        str(x) for x in (raw.get("document_ids_ref") or [])
                    ],
                    fact_content=str(raw.get("fact_content") or ""),
                    confidence=float(raw.get("confidence") or 0.5),
                    trace_id=str(raw.get("trace_id") or ""),
                    status=str(raw.get("status") or "active"),
                    version=int(raw.get("version") or 1),
                    created_at=float(raw.get("created_at") or time.time()),
                )
                if entry.fact_content:
                    bb._by_topic[entry.topic] = entry
            except (TypeError, ValueError):
                continue
        return bb

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [
            t
            for t, e in self._by_topic.items()
            if now - e.created_at > self._ttl_s
        ]
        for t in expired:
            del self._by_topic[t]

    def _enforce_capacity(self) -> None:
        if len(self._by_topic) <= self._capacity:
            return
        ranked = sorted(
            self._by_topic.items(),
            key=lambda kv: (kv[1].confidence, kv[1].created_at),
        )
        for topic, _ in ranked[: len(self._by_topic) - self._capacity]:
            del self._by_topic[topic]

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
                    "action": "plan.blackboard",
                    "trace_id": trace_id,
                    "input_text": entry.topic[:200],
                    "output_text": json.dumps(
                        {
                            "entry_id": entry.entry_id,
                            "topic": entry.topic,
                            "source_agent_id": entry.source_agent_id,
                            "document_ids_ref": entry.document_ids_ref,
                            "fact_content": entry.fact_content[:300],
                            "confidence": entry.confidence,
                            "version": entry.version,
                            "status": entry.status,
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
    topic: str | None = None,
) -> BlackboardEntry | None:
    text = str(outcome.get("output") or outcome.get("text") or "").strip()
    if not text or outcome.get("skipped"):
        return None
    if len(text) > _MAX_FACT_CHARS:
        return None
    conf = 0.9 if outcome.get("ok", True) else 0.4
    return BlackboardEntry(
        topic=topic or f"step.{step_id}",
        source_agent_id=f"{step_id}:{capability_id}",
        document_ids_ref=list(document_ids_ref or []),
        fact_content=text,
        confidence=conf,
    )
