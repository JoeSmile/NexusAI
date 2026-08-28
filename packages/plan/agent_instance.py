"""AgentInstance spawn lifecycle — independent trace + audit (Task 62 P1)."""

from __future__ import annotations

import json
import time
import uuid
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.audit import write_audit_sync


class AgentInstanceStatus(StrEnum):
    SPAWNED = "spawned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentInstance(BaseModel):
    instance_id: str
    agent_type_id: str
    parent_run_id: str
    trace_id: str
    step_id: str
    capability_id: str
    task: str = ""
    attempt: int = Field(default=1, ge=1, le=16)
    max_attempts: int = Field(default=1, ge=1, le=16)
    model_name: str | None = None
    escalated_model: str | None = None
    status: AgentInstanceStatus = AgentInstanceStatus.SPAWNED
    created_at: float = Field(default_factory=time.time)
    completed_at: float | None = None
    error: str | None = None

    model_config = ConfigDict(extra="ignore")

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def spawn_trace_id(parent_trace_id: str, step_id: str, attempt: int = 1) -> str:
    suffix = (step_id or uuid.uuid4().hex[:8]).replace(":", "_")[:32]
    base = (parent_trace_id or "run").strip() or "run"
    if attempt > 1:
        return f"{base}:spawn:{suffix}:r{attempt}"
    return f"{base}:spawn:{suffix}"


def spawn_agent_instance(
    *,
    agent_type_id: str,
    parent_run_id: str,
    step_id: str,
    capability_id: str,
    task: str = "",
    attempt: int = 1,
    max_attempts: int = 1,
    model_name: str | None = None,
    escalated_model: str | None = None,
) -> AgentInstance:
    trace_id = spawn_trace_id(parent_run_id, step_id, attempt)
    instance = AgentInstance(
        instance_id=uuid.uuid4().hex,
        agent_type_id=agent_type_id,
        parent_run_id=parent_run_id,
        trace_id=trace_id,
        step_id=step_id,
        capability_id=capability_id,
        task=(task or "")[:2000],
        attempt=attempt,
        max_attempts=max_attempts,
        model_name=model_name,
        escalated_model=escalated_model,
        status=AgentInstanceStatus.SPAWNED,
    )
    return instance


def mark_instance_running(instance: AgentInstance) -> AgentInstance:
    return instance.model_copy(update={"status": AgentInstanceStatus.RUNNING})


def complete_agent_instance(
    instance: AgentInstance,
    *,
    output_summary: str = "",
) -> AgentInstance:
    updated = instance.model_copy(
        update={
            "status": AgentInstanceStatus.COMPLETED,
            "completed_at": time.time(),
        },
    )
    return updated


def fail_agent_instance(
    instance: AgentInstance,
    error: str,
) -> AgentInstance:
    updated = instance.model_copy(
        update={
            "status": AgentInstanceStatus.FAILED,
            "completed_at": time.time(),
            "error": error[:500],
        },
    )
    return updated


def audit_instance_event(
    *,
    event: Literal["spawned", "running", "completed", "failed"],
    instance: AgentInstance,
    tenant_id: str = "",
    user_id: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    body = {
        "event": event,
        "instance_id": instance.instance_id,
        "agent_type_id": instance.agent_type_id,
        "parent_run_id": instance.parent_run_id,
        "step_id": instance.step_id,
        "capability_id": instance.capability_id,
        "attempt": instance.attempt,
        "max_attempts": instance.max_attempts,
        "status": instance.status,
        **(extra or {}),
    }
    try:
        write_audit_sync(
            {
                "tenant_id": tenant_id or "default",
                "user_id": user_id or "system",
                "action": "plan.agent_instance",
                "trace_id": instance.trace_id,
                "parent_trace_id": instance.parent_run_id,
                "input_text": instance.agent_type_id[:200],
                "output_text": json.dumps(body, ensure_ascii=False)[:2000],
                "model": "agent_instance",
            }
        )
    except Exception:
        pass


def record_instance_on_state(
    state: dict[str, Any],
    instance: AgentInstance,
) -> None:
    rows = list(state.get("agent_instances") or [])
    for i, row in enumerate(rows):
        if isinstance(row, dict) and row.get("instance_id") == instance.instance_id:
            rows[i] = instance.to_dict()
            state["agent_instances"] = rows
            return
    rows.append(instance.to_dict())
    state["agent_instances"] = rows
