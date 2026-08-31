"""Builtin tool CapabilitySpec definitions (Task 66 slice 1)."""

from __future__ import annotations

from typing import Any

from packages.capability.builtin.contracts import (
    generic_contract,
    memory_search_contract,
    memory_write_contract,
    rag_search_contract,
    web_search_contract,
)
from packages.capability.models import CapabilityKind, CapabilityProvider

_STR = {"type": "string"}


def _tool(
    cap_id: str,
    *,
    description: str,
    contract: dict[str, Any],
    risk_level: str,
    permission: str = "chat:write",
    requires_approval: bool = False,
    exec_policy: dict[str, Any] | None = None,
    isolation_mode: str = "direct",
) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "executor": "builtin",
        "builtin_handler": cap_id,
        "risk_level": risk_level,
        "requires_approval": requires_approval,
        "isolation_mode": isolation_mode,
        "governance": True,
        "tool_contract": contract,
    }
    if exec_policy:
        spec["exec_policy"] = exec_policy
    return {
        "id": cap_id,
        "name": cap_id,
        "kind": CapabilityKind.TOOL.value,
        "provider": CapabilityProvider.NEXUSAI.value,
        "description": description,
        "permission": permission,
        "spec": spec,
    }


BUILTIN_TOOL_SPECS: list[dict[str, Any]] = [
    _tool(
        "rag.search",
        description="RAG knowledge search",
        contract=rag_search_contract(),
        risk_level="low",
        permission="rag:read",
    ),
    _tool(
        "web.search",
        description="Web search with SSRF guard",
        contract=web_search_contract(),
        risk_level="low",
    ),
    _tool(
        "memory.search",
        description="Semantic warm memory search",
        contract=memory_search_contract(),
        risk_level="low",
        permission="memory:read",
    ),
    _tool(
        "memory.write",
        description="Write warm user memory",
        contract=memory_write_contract(),
        risk_level="medium",
        permission="memory:write",
    ),
    _tool(
        "im.notify",
        description="Send in-app notification to user",
        contract=generic_contract(
            "im.notify",
            description="Dispatch notification via configured channels.",
            input_props={
                "type": _STR,
                "summary": _STR,
                "run_id": _STR,
            },
            required=["type", "summary"],
        ),
        risk_level="medium",
    ),
    _tool(
        "calendar.query",
        description="Query calendar events in range",
        contract=generic_contract(
            "calendar.query",
            description="List calendar events for a date range.",
            input_props={"from": _STR, "to": _STR},
            required=["from", "to"],
            idempotent=True,
            idempotency_key_args=["from", "to"],
        ),
        risk_level="low",
    ),
    _tool(
        "calendar.create",
        description="Create calendar event",
        contract=generic_contract(
            "calendar.create",
            description="Create a calendar event with title and time window.",
            input_props={"title": _STR, "start": _STR, "end": _STR},
            required=["title", "start", "end"],
            idempotent=True,
            idempotency_key_args=["title", "start", "end"],
        ),
        risk_level="medium",
    ),
    _tool(
        "mail.draft",
        description="Draft outbound email",
        contract=generic_contract(
            "mail.draft",
            description="Create an email draft without sending.",
            input_props={"to": _STR, "subject": _STR, "body": _STR},
            required=["to", "subject", "body"],
            idempotent=True,
            idempotency_key_args=["to", "subject"],
        ),
        risk_level="medium",
    ),
    _tool(
        "mail.send",
        description="Send email (approval required)",
        contract=generic_contract(
            "mail.send",
            description="Send email after human approval gate.",
            input_props={"draft_id": _STR},
            required=["draft_id"],
            idempotent=True,
            idempotency_key_args=["draft_id"],
        ),
        risk_level="high",
        requires_approval=True,
    ),
    _tool(
        "docx.generate",
        description="Generate Word document from template",
        contract=generic_contract(
            "docx.generate",
            description="Render a docx file from template and variables.",
            input_props={"template": _STR, "variables": {"type": "object"}},
            required=["template"],
        ),
        risk_level="medium",
    ),
    _tool(
        "sql.query",
        description="Read-only SQL against allowlisted views",
        contract=generic_contract(
            "sql.query",
            description="Execute read-only SQL on tenant allowlisted relations.",
            input_props={"sql": _STR, "limit": {"type": "integer"}},
            required=["sql"],
        ),
        risk_level="high",
        permission="analytics:read",
        exec_policy={"timeout_s": 15, "isolation_mode": "subprocess"},
        isolation_mode="subprocess",
    ),
    _tool(
        "analytics.summary",
        description="Aggregate analytics summary",
        contract=generic_contract(
            "analytics.summary",
            description="Return KPI summary for a metric and time window.",
            input_props={"metric": _STR, "window": _STR},
            required=["metric"],
        ),
        risk_level="low",
        permission="analytics:read",
    ),
    _tool(
        "code.exec",
        description="Execute sandboxed code snippet",
        contract=generic_contract(
            "code.exec",
            description="Run restricted code in isolated subprocess.",
            input_props={"language": _STR, "code": _STR},
            required=["language", "code"],
        ),
        risk_level="critical",
        requires_approval=True,
        exec_policy={"timeout_s": 10, "isolation_mode": "sandbox"},
        isolation_mode="sandbox",
    ),
    _tool(
        "deploy.release",
        description="Trigger deployment release",
        contract=generic_contract(
            "deploy.release",
            description="Promote artifact to target environment after approval.",
            input_props={"service": _STR, "version": _STR, "env": _STR},
            required=["service", "version", "env"],
        ),
        risk_level="critical",
        requires_approval=True,
        permission="admin:write",
    ),
    _tool(
        "sys.metrics",
        description="Read system health metrics",
        contract=generic_contract(
            "sys.metrics",
            description="Return process and dependency health metrics snapshot.",
            input_props={"component": _STR},
            idempotent=True,
            idempotency_key_args=["component"],
        ),
        risk_level="low",
        permission="admin:read",
    ),
    _tool(
        "plan.status",
        description="Read agent plan execution status",
        contract=generic_contract(
            "plan.status",
            description="Return current plan node status for a run.",
            input_props={"run_id": _STR, "plan_id": _STR},
            required=["run_id"],
            idempotent=True,
            idempotency_key_args=["run_id"],
        ),
        risk_level="low",
    ),
    _tool(
        "blackboard.search",
        description="Search session blackboard entries (cold path / topic filter)",
        contract=generic_contract(
            "blackboard.search",
            description="Filter blackboard facts by topic prefix, keyword, confidence.",
            input_props={
                "blackboard": {"type": "array"},
                "topic": _STR,
                "keyword": _STR,
                "min_confidence": {"type": "number"},
                "limit": {"type": "integer"},
            },
            required=[],
            idempotent=True,
        ),
        risk_level="low",
        permission="chat:read",
    ),
    _tool(
        "image.describe",
        description="Describe a session image attachment via tenant vision BYOK or OCR",
        contract=generic_contract(
            "image.describe",
            description="Return a caption for an image attachment in the current chat session.",
            input_props={
                "attachment_id": _STR,
                "session_id": _STR,
                "query_hint": _STR,
            },
            required=["attachment_id", "session_id"],
            idempotent=True,
            idempotency_key_args=["attachment_id", "session_id"],
        ),
        risk_level="low",
        permission="chat:write",
    ),
]
