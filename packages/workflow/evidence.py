"""Evidence items for workflow node outputs (Wave D)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class EvidenceItem(BaseModel):
    kind: Literal["quote", "link", "doc_ref", "metric"] = "quote"
    title: str
    snippet: str | None = None
    uri: str | None = None
    source_node_id: str | None = None


def evidence_from_rag_sources(
    sources: list[dict[str, Any]] | None,
    *,
    node_id: str,
) -> list[dict[str, Any]]:
    """仅映射真实检索 sources；无命中 → []（禁止用 answer 合成）。"""
    items: list[EvidenceItem] = []
    for i, src in enumerate(sources or []):
        content = str(src.get("content") or "")
        meta_raw = src.get("metadata")
        meta = meta_raw if isinstance(meta_raw, dict) else {}
        title = str(meta.get("title") or meta.get("source") or f"source_{i + 1}")
        items.append(
            EvidenceItem(
                kind="quote",
                title=title[:200],
                snippet=content[:500] if content else None,
                source_node_id=node_id,
            )
        )
    return [e.model_dump() for e in items]


def node_output(*, result: Any, evidence: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"result": result, "evidence": evidence or []}
