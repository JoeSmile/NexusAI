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

from .blackboard_preprocess import preprocess_blackboard_write
from .topic_registry import TopicRegistryError, validate_topic

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
    risk_level: str = "normal"
    dirty: bool = False
    error: str | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_high_risk(entry: BlackboardEntry) -> bool:
    return entry.risk_level == "high" or entry.topic.startswith("risk.")


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
        self._by_id: dict[str, BlackboardEntry] = {}

    def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        self._evict_expired()
        entry = self._by_id.get(entry_id)
        return entry.to_dict() if entry is not None else None

    def begin_pending(
        self,
        *,
        topic: str,
        fact_content: str = "…",
        source_agent_id: str,
        document_ids_ref: list[str] | None = None,
        confidence: float = 0.5,
        tenant_id: str = "default",
        user_id: str = "system",
        trace_id: str = "",
    ) -> str:
        topic_key = validate_topic(topic.strip())
        self._evict_expired()
        prev = self._by_topic.get(topic_key)
        version = (prev.version + 1) if prev else 1
        placeholder = (fact_content or "…").strip() or "…"
        entry = BlackboardEntry(
            entry_id=str(uuid.uuid4()),
            topic=topic_key,
            source_agent_id=source_agent_id,
            document_ids_ref=list(document_ids_ref or []),
            fact_content=placeholder[:_MAX_FACT_CHARS],
            confidence=float(confidence),
            trace_id=trace_id,
            status="pending",
            version=version,
            created_at=time.time(),
        )
        self._register_entry(entry)
        self._audit_add(entry, tenant_id=tenant_id, user_id=user_id, trace_id=trace_id)
        return entry.entry_id

    def complete_entry(
        self,
        entry_id: str,
        *,
        fact_content: str | None = None,
        confidence: float | None = None,
        document_ids_ref: list[str] | None = None,
        tenant_id: str = "default",
        user_id: str = "system",
        trace_id: str = "",
    ) -> bool:
        entry = self._by_id.get(entry_id)
        if entry is None or entry.status != "pending":
            return False
        if fact_content is not None:
            fact_raw = fact_content.strip()
            if not fact_raw:
                return False
            fact, _flags = sanitize_fragment(fact_raw, max_chars=_MAX_FACT_CHARS)
            entry.fact_content = fact[:_MAX_FACT_CHARS]
        if confidence is not None:
            entry.confidence = float(confidence)
        if document_ids_ref is not None:
            entry.document_ids_ref = list(document_ids_ref)
        entry.status = "completed"
        entry.error = None
        entry.dirty = True
        self._register_entry(entry)
        self._audit_add(entry, tenant_id=tenant_id, user_id=user_id, trace_id=trace_id)
        return True

    def fail_entry(
        self,
        entry_id: str,
        *,
        error: str = "",
        tenant_id: str = "default",
        user_id: str = "system",
        trace_id: str = "",
    ) -> bool:
        entry = self._by_id.get(entry_id)
        if entry is None:
            return False
        entry.status = "failed"
        entry.error = (error or "")[:500] or None
        self._register_entry(entry)
        self._audit_add(entry, tenant_id=tenant_id, user_id=user_id, trace_id=trace_id)
        return True

    def fail_stale_pending(
        self,
        *,
        error: str = "run_ended_incomplete",
        tenant_id: str = "default",
        user_id: str = "system",
        trace_id: str = "",
    ) -> int:
        count = 0
        for entry in list(self._by_id.values()):
            if entry.status == "pending":
                if self.fail_entry(
                    entry.entry_id,
                    error=error,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    trace_id=trace_id,
                ):
                    count += 1
        return count

    def cas_update_topic(
        self,
        topic: str,
        expected_version: int,
        entry: BlackboardEntry,
        *,
        tenant_id: str = "default",
        user_id: str = "system",
        trace_id: str = "",
    ) -> bool:
        topic_key = validate_topic(topic.strip())
        prev = self._by_topic.get(topic_key)
        if prev is None or prev.version != expected_version:
            self._audit_cas_conflict(
                topic_key,
                expected_version=expected_version,
                actual_version=prev.version if prev else -1,
                tenant_id=tenant_id,
                user_id=user_id,
                trace_id=trace_id,
            )
            return False
        updated = BlackboardEntry(
            entry_id=entry.entry_id or str(uuid.uuid4()),
            topic=topic_key,
            source_agent_id=entry.source_agent_id,
            document_ids_ref=list(entry.document_ids_ref),
            fact_content=entry.fact_content[:_MAX_FACT_CHARS],
            confidence=float(entry.confidence),
            trace_id=entry.trace_id or trace_id,
            status=entry.status or "completed",
            version=expected_version + 1,
            risk_level=entry.risk_level,
            dirty=entry.dirty,
            error=entry.error,
            created_at=time.time(),
        )
        self._register_entry(updated)
        self._enforce_capacity()
        self._audit_add(updated, tenant_id=tenant_id, user_id=user_id, trace_id=trace_id)
        return True

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
        skip_topic_validation: bool = False,
        risk_level: str = "normal",
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
        try:
            topic_key = (
                validate_topic(topic.strip())
                if not skip_topic_validation
                else (topic.strip() or "fact.general")
            )
        except TopicRegistryError:
            raise
        effective_risk = "high" if topic_key.startswith("risk.") else risk_level
        prev = self._by_topic.get(topic_key)
        pre = preprocess_blackboard_write(
            topic=topic_key,
            fact_content=fact,
            confidence=float(confidence),
            document_ids_ref=list(document_ids_ref or []),
            prev=prev,
        )
        if pre.action in {"dedup_skip", "confidence_suppress"}:
            self._audit_preprocess(
                topic_key,
                pre.action,
                pre.detail,
                tenant_id=tenant_id,
                user_id=user_id,
                trace_id=trace_id,
            )
            return False

        write_fact = pre.fact_content or fact
        write_conf = float(pre.confidence if pre.confidence is not None else confidence)
        write_docs = list(
            pre.document_ids_ref if pre.document_ids_ref is not None else (document_ids_ref or [])
        )
        version = (prev.version + 1) if prev else 1
        status = "completed"
        if pre.action == "semantic_conflict" and prev is not None:
            prev.status = "conflict"
            status = "conflict"
        elif pre.action == "homogeneous_merge" and prev is not None:
            status = "completed"

        entry = BlackboardEntry(
            entry_id=str(uuid.uuid4()),
            topic=topic_key,
            source_agent_id=source_agent_id,
            document_ids_ref=write_docs,
            fact_content=write_fact[:_MAX_FACT_CHARS],
            confidence=write_conf,
            trace_id=trace_id,
            status=status,
            version=version,
            risk_level=effective_risk,
            dirty=prev is not None,
            created_at=time.time(),
        )
        self._register_entry(entry)
        self._enforce_capacity()
        if pre.action != "insert":
            self._audit_preprocess(
                topic_key,
                pre.action,
                pre.detail,
                tenant_id=tenant_id,
                user_id=user_id,
                trace_id=trace_id,
            )
        self._audit_add(entry, tenant_id=tenant_id, user_id=user_id, trace_id=trace_id)
        return True

    def list_entries(self) -> list[dict[str, Any]]:
        self._evict_expired()
        return [e.to_dict() for e in sorted(self._by_topic.values(), key=lambda x: x.created_at)]

    def hot_entries(self, *, limit: int = _HOT_LIMIT) -> list[BlackboardEntry]:
        return self.project_entries(limit=limit)

    def cold_entries(self) -> list[BlackboardEntry]:
        """Entries outside hot projection (full retention for blackboard_search)."""
        self._evict_expired()
        hot_ids = {e.entry_id for e in self.hot_entries()}
        return [
            e
            for e in sorted(self._by_topic.values(), key=lambda x: x.created_at)
            if e.entry_id not in hot_ids
        ]

    def project_entries(
        self,
        *,
        filter_topic: str | None = None,
        min_confidence: float = _MIN_CONFIDENCE,
        only_status: frozenset[str] | None = None,
        limit: int = _HOT_LIMIT,
    ) -> list[BlackboardEntry]:
        """Hot projection — spec §7.10 filterTopic/minConfidence/onlyStatus/limit."""
        from .topic_registry import match_topic_prefix

        self._evict_expired()
        statuses = only_status or frozenset({"active", "completed", "conflict"})
        rows = [
            e
            for e in self._by_topic.values()
            if e.status in statuses
            and e.confidence >= min_confidence
            and match_topic_prefix(e.topic, filter_topic)
        ]
        rows.sort(key=lambda e: (e.confidence, e.created_at), reverse=True)
        return rows[:limit]

    def search(
        self,
        *,
        topic: str | None = None,
        keyword: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        """Cold-path search for blackboard_search capability (§7.10)."""
        from .topic_registry import match_topic_prefix

        self._evict_expired()
        kw = (keyword or "").strip().lower()
        out: list[BlackboardEntry] = []
        for e in sorted(self._by_topic.values(), key=lambda x: x.created_at, reverse=True):
            if e.confidence < min_confidence:
                continue
            if not match_topic_prefix(e.topic, topic):
                continue
            if kw and kw not in e.fact_content.lower() and kw not in e.topic.lower():
                continue
            out.append(e)
            if len(out) >= limit:
                break
        return [e.to_dict() for e in out]

    def project_for_prompt(
        self,
        *,
        seen_fact_ids: set[str] | None = None,
        filter_topic: str | None = None,
        limit: int = _HOT_LIMIT,
    ) -> list[BlackboardEntry]:
        """Incremental hot projection — skip seen unless dirty/conflict."""
        from .topic_registry import match_topic_prefix

        seen = seen_fact_ids or set()
        candidates = self.project_entries(
            filter_topic=filter_topic,
            only_status=frozenset({"completed", "conflict", "failed"}),
            limit=max(limit, _HOT_LIMIT),
        )
        out: list[BlackboardEntry] = []
        for entry in candidates:
            if entry.status == "failed" and not entry.dirty:
                continue
            if (
                entry.entry_id not in seen
                or entry.dirty
                or entry.status == "conflict"
            ):
                out.append(entry)
        out.sort(
            key=lambda e: (
                0 if e.status == "conflict" else 1,
                -e.confidence,
                -e.created_at,
            )
        )
        base = out[:limit]
        included = {e.entry_id for e in base}
        for entry in self._by_topic.values():
            if not is_high_risk(entry):
                continue
            if entry.status not in frozenset({"completed", "conflict"}):
                continue
            if entry.confidence < _MIN_CONFIDENCE:
                continue
            if not match_topic_prefix(entry.topic, filter_topic):
                continue
            if entry.entry_id in included:
                continue
            base.append(entry)
            included.add(entry.entry_id)
        return base

    def mark_seen(
        self,
        seen_fact_ids: set[str],
        entry_ids: list[str],
    ) -> set[str]:
        merged = set(seen_fact_ids) | set(entry_ids)
        for eid in entry_ids:
            entry = self._by_id.get(eid)
            if entry is not None:
                entry.dirty = False
        return merged

    def synthesize(
        self,
        goal: str = "",
        *,
        seen_fact_ids: set[str] | None = None,
    ) -> tuple[str, list[str]]:
        lines: list[str] = []
        if goal:
            lines.append(f"目标：{goal}")
        used = 0
        entries = self.project_for_prompt(seen_fact_ids=seen_fact_ids or set())
        newly_seen: list[str] = []
        for e in entries:
            newly_seen.append(e.entry_id)
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
        return "\n".join(lines), newly_seen

    def synthesize_legacy(self, goal: str = "") -> str:
        text, _ = self.synthesize(goal, seen_fact_ids=set())
        return text

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
                    risk_level=str(raw.get("risk_level") or "normal"),
                    dirty=bool(raw.get("dirty") or False),
                    error=raw.get("error"),
                    created_at=float(raw.get("created_at") or time.time()),
                )
                if entry.fact_content:
                    bb._register_entry(entry)
            except (TypeError, ValueError):
                continue
        return bb

    def _register_entry(self, entry: BlackboardEntry) -> None:
        if not entry.entry_id:
            entry.entry_id = str(uuid.uuid4())
        prev = self._by_topic.get(entry.topic)
        if prev is not None and prev.entry_id != entry.entry_id:
            self._by_id.pop(prev.entry_id, None)
        self._by_topic[entry.topic] = entry
        self._by_id[entry.entry_id] = entry

    def _evict_expired(self) -> None:
        now = time.time()
        expired_topics = [
            t
            for t, e in self._by_topic.items()
            if now - e.created_at > self._ttl_s
        ]
        for topic in expired_topics:
            entry = self._by_topic.pop(topic, None)
            if entry is not None:
                self._by_id.pop(entry.entry_id, None)

    def _enforce_capacity(self) -> None:
        if len(self._by_topic) <= self._capacity:
            return
        evictable = sorted(
            (
                (topic, entry)
                for topic, entry in self._by_topic.items()
                if not is_high_risk(entry)
            ),
            key=lambda kv: (kv[1].confidence, kv[1].created_at),
        )
        to_remove = len(self._by_topic) - self._capacity
        for topic, entry in evictable[:to_remove]:
            self._by_topic.pop(topic, None)
            self._by_id.pop(entry.entry_id, None)

    def _audit_cas_conflict(
        self,
        topic: str,
        *,
        expected_version: int,
        actual_version: int,
        tenant_id: str,
        user_id: str,
        trace_id: str,
    ) -> None:
        try:
            write_audit_sync(
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "action": "plan.blackboard_cas_conflict",
                    "trace_id": trace_id,
                    "input_text": topic[:200],
                    "output_text": json.dumps(
                        {
                            "topic": topic,
                            "expected_version": expected_version,
                            "actual_version": actual_version,
                        },
                        ensure_ascii=False,
                    )[:2000],
                    "model": "blackboard",
                }
            )
        except Exception:
            pass

    def _audit_preprocess(
        self,
        topic: str,
        action: str,
        detail: str,
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
                    "action": "plan.blackboard_preprocess",
                    "trace_id": trace_id,
                    "input_text": topic[:200],
                    "output_text": json.dumps(
                        {"topic": topic, "action": action, "detail": detail},
                        ensure_ascii=False,
                    )[:2000],
                    "model": "blackboard",
                }
            )
        except Exception:
            pass

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
